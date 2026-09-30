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

### [DONE] PROMPT-003 Audit Phase 4E — AI Provider Integration, Supply-Chain & Infrastructure Configuration

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-19
- **Assigned subsystem**: §4 Audit Phase 4E — AI integration: `backend/app/ai_config.py`, `ai_catalog.py`, `ai_ollama.py`, `ai_startup.py`, `ai_migration.py`, `app/llm.py`, `worker/llm_escalation.py` (detection's second-opinion mechanism per §0), `app/crypto.py` (Fernet-at-rest), `app/data/models_dev_catalog.json`, the AI settings/portal inside `app/routers/settings.py` (legacy Gemini/Ollama adapters + `/api/settings/ai/*`), the `scan_tasks.py`→`escalate_scan` seam, and `app/routers/reports.py` only as the sole WeasyPrint call site (advisory reachability). Supply chain & infra: `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json` + `frontend/pnpm-lock.yaml`, `backend/Dockerfile.app`, `backend/Dockerfile.worker`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`, `backend/tools/check_torch_osv.py`, `scripts/*.ps1` (secrets generation/guards only). Builds on, not re-derived: AUDIT-2B-6 (dependency hygiene) and the 4C handoff note about the legacy `PUT /api/settings/ollama` write path.

- **Method & environment (Rule 13)**:
  - Full Step 3 cold read of every in-scope file, tracing callers/callees into the scan path (`scan_tasks.py:315-327`), the HTTP surface (`settings.py` AI routes) and the litellm layer.
  - Live stack used read-only for state attestation (`wardress-app-1` healthy on :8321, worker/beat/db/redis up; no container was started or stopped): `ai_providers` = 1 row — the auto-provisioned `Ollama (local)`, `provider_type=ollama`, `base_url=http://ollama:11434`, `enabled=t`, `validation_status=unknown`, `ai_seed_done` sentinel present; `ai_task_assignments` = 0; `model_catalog` = 7850 models / 222 providers (a live models.dev sync is retained in the DB); the `ollama` profile container is NOT running and `socket.getaddrinfo('ollama')` **fails inside the app container** (`gaierror -5`); deployed versions: `weasyprint 69.0` in the app image, `torch 2.13.0+cpu` in the worker; `CREDENTIALS_ENCRYPTION_KEY` set.
  - Empirical measurement instead of arithmetic assertion (Rule 4/18): two scratch probes under `Prompts/Pending/Finders/PROMPT-003/scratch/` (preserved for reproducibility, per the effort's precedent) drive the production `validate_provider_call` against a local socket server that accepts and never answers, with the production 30 s timeout, three passes each.
  - Supply-chain sweep with the tooling actually present: `uv`-managed `pip-audit 2.10.1` over the installed (locked) environment, `backend/tools/check_torch_osv.py` against the live OSV API, and `pnpm audit --audit-level high` (the exact CI command) in `frontend/`. Limits stated honestly below (pip-audit cannot see torch; the frontend gate is severity-thresholded; no SCA/lockfile-diff tooling or OSV batch client exists in this environment, so "vulnerability sweep" here means exactly these three gates).

- **Findings**:

    - **ID**: AUDIT-4E-1
    - **Title**: The SSRF policy is skipped by one `ai_providers.base_url` writer and never re-checked on the AI execution path — the invariant "every URL the platform fetches goes through `assert_url_allowed`" holds for sites/probes/favicons/imports/remediations and fails for AI providers
    - **Severity**: **Critical** — per Rule 12 ("The SSRF policy is sacred … Any finding here is automatically Critical") and §6.4's first bullet ("SSRF/security boundary weakness"). Honest impact scoping, so remediation can prioritise correctly: the private-network allowance is *documented and deliberate* for the two local provider types (`ai_config.validate_base_url` gates it on `provider_type in (OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE)`), so internal reachability via a local-LLM provider is by design; what is NOT by design is that one supported writer stores a URL that never passed even the scheme/credential/DNS checks, and that the two paths performing the actual outbound call (`POST …/validate`, `resolve_task`) consult nothing at all — the policy is applied per call site by memory rather than where the URL reaches litellm.
    - **Subsystem / file(s)**: `backend/app/routers/settings.py:548-583` (`put_ollama`, create branch passes `validate_url=False`), `backend/app/ai_config.py:112-137` (`create_provider`) and `:140-166` (`update_provider` — the *update* branch does validate), `backend/app/routers/settings.py:739-772` (`validate_ai_provider` → `app/llm.validate_provider_call` → `_build_router` → `_deployments`, no check), `backend/app/llm.py:283-359` (`resolve_task` — the path `worker/scan_tasks.py:316` uses for detection escalation) and `app/llm.py:128-160` (`_litellm_api_base`/`_deployments` hand `provider.base_url` to litellm verbatim). Contrast (the Phase-16 fix): `settings.py:775-795` (`list_ollama_models`) and `:855-915` (`pull_ollama_model`) DO validate the effective URL at use time.
    - **Reproduction**: hermetic, committed-passing — `backend/tests/test_phase4e_ai_supplychain_repros.py` (4 tests): `test_legacy_put_ollama_create_branch_stores_unvalidated_base_url` (live HTTP: `PUT /api/settings/ollama` with `base_url="file:///etc/passwd"` → **200** and the URL stored; the same value via `POST /api/settings/ai/providers` → **422**); `test_validate_endpoint_never_consults_the_ssrf_policy` (spy on `settings.validate_base_url`: the validate endpoint returns 200 with `ok=false` and the spy saw **zero** calls); `test_ollama_models_endpoint_does_consult_the_ssrf_policy` (control: the sibling endpoint calls it once and 422s); `test_resolve_task_hands_unvalidated_base_url_to_litellm` (an `ftp://user:secret@…` base_url reaches `router.model_list[0]["litellm_params"]["api_base"]` while `assert_url_allowed` on the same string raises `SSRFBlockedError`).
    - **Root cause**: validation is a *save-time* responsibility owned by the service layer, and `create_provider(validate_url=False)` exists as an escape hatch for trusted migration input. Because readers never re-validate, the escape hatch plus the two endpoints nobody retrofitted is the whole gap. The migration/seed comments (correctly) justify skipping save-time DNS for Docker-internal hostnames — which is exactly why a use-time check is the right home for the invariant.
    - **Proposed remedy category**: policy application refactor — validate at the single point a provider's `base_url` becomes a litellm deployment (`_build_router`/`resolve_task`) so every reader is covered by construction; make any `validate_url=False` caller carry an explicit, audited reason; extend Phase 16's use-time pattern to `validate_ai_provider`. Not implemented here (Rule 1).
    - **Source**: kickoff hunt list ("SSRF safety on custom provider endpoints … validation at save AND at use"); Phase 4C handoff note.

    - **ID**: AUDIT-4E-2
    - **Title**: The models.dev catalog fetch is outside the SSRF policy entirely and rides an unpinned httpx client
    - **Severity**: **Critical** — Rule 12 again: it directly contradicts `app/ssrf.py`'s own documented contract ("Every URL the platform is asked to fetch goes through `assert_url_allowed` before any network activity"). Honest impact scoping: `CATALOG_URL` is a compile-time constant (`https://models.dev/catalog.json`), so the attacker-influenced surface is DNS resolution only, and the payload is consumed as reference data (normalized into `model_catalog*` rows) and never executed — practical risk well below AUDIT-4E-1's. The pinning gap is the same class already logged as AUDIT-4D-3 (favicon). Logged Critical because the mechanical rule is explicit and the repair is cheap.
    - **Subsystem / file(s)**: `backend/app/ai_catalog.py:36` (`CATALOG_URL`), `:144-158` (`fetch_live_catalog` — `httpx.AsyncClient(timeout=20)`, no `transport=`, no `assert_url_allowed`, `follow_redirects` left at httpx's default). Contrast: `app/remediation.py:182-184`, `app/routers/imports.py:178-185`, `worker/probe.py:201-211` all build `SSRFPinningTransport`.
    - **Reproduction**: hermetic, committed-passing — `test_fetch_live_catalog_never_consults_the_ssrf_policy` (a spy replaces `app.ssrf.assert_url_allowed` with a function that records then raises: the fetch completes, the spy was **never called**, and the only URL requested is `CATALOG_URL`) and `test_fetch_live_catalog_builds_an_unpinned_client` (a recording `AsyncClient` subclass shows the constructed kwargs contain `timeout=20` and **no `transport`**).
    - **Root cause**: same as 4E-1 — the policy is applied per call site rather than at a shared outbound-fetch factory. The catalog was written as "reference data, no secrets" and its URL assumed safe because it is a constant; true of the literal, not of the resolution.
    - **Proposed remedy category**: policy application — route this fetch through the pinning transport (or a shared `safe_client()` factory, see O-4E-2); if the constant-URL assumption is to stand, state it explicitly in `ssrf.py` so the documented invariant is not silently false. Not implemented here.
    - **Source**: kickoff hunt list ("SSRF safety … the models.dev catalog fetch … pinning transport vs unpinned httpx"); Rule 13 docstring-vs-reality divergence.

    - **ID**: AUDIT-4E-3
    - **Title**: A hung provider stalls its caller for one full 30 s timeout *per key/deployment*, and neither detection's escalation nor the explain endpoint passes any overall deadline
    - **Severity**: **Medium** — degradation is graceful and total (the escalation cannot fail a scan: `escalate_scan` converts every outcome to an evidence string, and the verdict stands), but the measured stall scales linearly with the key pool (one litellm deployment per key) inside a scan whose Celery soft limit is 420 s, so a hung-but-connected provider can push capture+detection+escalation past `task_soft_time_limit` and turn a silent degradation into a soft-time-limit kill (row recovered by the 10-min stale sweep = wasted work + failed-scan noise). Not High: the failure is bounded, recoverable and never silent on the scan row.
    - **Subsystem / file(s)**: `backend/app/llm.py:82-91` (`_REQUEST_TIMEOUT=30`, `_NUM_RETRIES=2`, `_ALLOWED_FAILS=0`, `_COOLDOWN_SECONDS=60`), `:144-160` (one deployment per key), `:255-274` (`_build_router`), `worker/llm_escalation.py:59-78` (`escalate_scan`, no `wait_for`), `worker/scan_tasks.py:315-327` (awaited inline in `_run_scan`), `worker/celery_app.py:44-45` (soft 420 / hard 480), `app/explain.py` (same `generate` path on a request).
    - **Reproduction**: measured, 3 passes each (scratch probes `probe_ai_llm_hang_budget.py`, `probe_ai_llm_hang_multikey.py` — local server accepts and never answers; production timeout unchanged): **1 deployment → 30.61 s / 30.03 s / 30.02 s** (variance 0.58 s, single attempt: `allowed_fails=0` cools the only deployment after its first failure); **2 keyed deployments → 60.67 s / 60.08 s / 60.05 s** (variance 0.62 s) — i.e. exactly one timeout per deployment, so a full 10-key pool is ~300 s and a fallback group can add a second such bill. Pinned hermetically (degenerate 0.4 s budget): `test_router_configures_a_per_model_group_retry_budget`, `test_every_key_is_its_own_deployment_and_its_own_timeout` (10 keys ⇒ 10 deployments × 30 s ≥ 300 s), `test_hung_deployment_degrades_after_one_timeout_budget`.
    - **Root cause**: the timeout is per-HTTP-call and per-deployment; no overall deadline is propagated from the caller that owns the real budget (the scan's soft limit, or the HTTP request). The layer contract ("any failure degrades silently") is met for correctness and unmet for latency.
    - **Proposed remedy category**: deadline propagation — wrap escalation/explain in `asyncio.wait_for` sized against the remaining scan budget (or a fraction of the soft limit), and/or cap a single call's exposure when the caller is a scan (one attempt). Not implemented here.
    - **Source**: kickoff hunt list ("graceful degradation when a provider fails/hangs … timeout budgets … a hung provider stalling detection"); Rule 13 (my first-pass arithmetic over-claimed 3 attempts; measurement corrected it in-phase).

    - **ID**: AUDIT-4E-4
    - **Title**: `weasyprint==69.0` is pinned into the runtime images with a published SSRF/arbitrary-file-read advisory (fix: 70.0), and the dependency gate the repo declares must fail on exactly this is currently failing
    - **Severity**: **Critical** — Rule 12's mechanical rule (the advisory is an SSRF/local-file-read class weakness in a component the API process imports and executes) plus §6.4's SSRF bullet; independently, `ci.yml:60-66` states "`|| true` is NOT used — a known vulnerability fails CI and must be triaged in WARDRESS_FIX_LOG.md", and the gate does fail (`EXITCODE=1`), so the declared contract is unmet on main. **Reachability caveat stated for honesty**: Wardress's single call site is `HTML(string=html).write_pdf()` with NO `stylesheets=`, NO `xmp_metadata=` and NO `url_fetcher=` (`app/routers/reports.py:195-199`), and the advisory's two exploit channels are precisely those parameters — so today's call shape does not expose them; the HTML itself is template-built with autoescape and embeds only data-URI screenshots plus an inline SVG, so no attacker-influenced URL enters the document either. If Phase 10 prefers to grade on demonstrated exploitability alone it may downgrade this to High — that must be a deliberate, recorded decision, not an omission.
    - **Subsystem / file(s)**: `backend/pyproject.toml:55` (`weasyprint==69.0`), `backend/uv.lock:2483-2485` (resolved 69.0), `.github/workflows/ci.yml:60-70`, `backend/app/routers/reports.py:195-199`, `backend/Dockerfile.app:40-52` (installs the Pango/Cairo/GDK-PixBuf runtime WeasyPrint needs). Live: `docker exec wardress-app-1 python -c "import weasyprint; …"` → **69.0**.
    - **Reproduction**: `cd backend; .venv\Scripts\python.exe -m pip_audit --skip-editable` → `Found 1 known vulnerability in 1 package / weasyprint 69.0 PYSEC-2026-3940 / Fix Versions 70.0`, **exit 1** (captured); OSV query for `weasyprint 69.0` → `GHSA-jf6q-chmf-3h3v` "weasyprint Has Server-Side Request Forgery (SSRF)" (details: `url_fetcher` bypassed for `xmp_metadata` and `stylesheets`, arbitrary local file read / SSRF, transitive through `@import`/`url()`).
    - **Root cause**: a version pin was set once and never re-audited against the advisory feed (the CI gate that would have caught it at the next push has been red since the advisory published); no Dependabot/Renovate job exists, so nothing re-raises it automatically.
    - **Proposed remedy category**: dependency bump (≥ 70.0 + `uv.lock` regen) — or, if the bump is deferred, an explicit `--ignore-vuln PYSEC-2026-3940` with the reachability argument written into the CI step and the fix log (a documented deviation, not a silent skip). Not implemented here (Rule 1).
    - **Source**: kickoff hunt list ("Vulnerability sweep on dependencies … state the method and its limits honestly").

    - **ID**: AUDIT-4E-5
    - **Title**: Every runtime image is a floating tag (no digest), including `ollama/ollama:latest`, which the AI layer's auto-provisioned provider points at
    - **Severity**: **Medium** — supply-chain/reproducibility drift (§6.4's "docs/infra drift that could mislead an operator"): a `docker compose pull` can change the database, broker or the local LLM engine under an existing install with no Wardress change; `ollama/ollama:latest` additionally makes the "fully offline LLM" path non-reproducible and can change `/api/tags`, `/api/show` and `/api/pull` behaviour the AI layer depends on (AUDIT-4E-7's deadline design assumes a cooperative stream).
    - **Subsystem / file(s)**: `docker-compose.yml:9` (`postgres:16`), `:24` (`redis:8-alpine`), `:158` (`ollama/ollama:latest`); `backend/Dockerfile.app:7` (`node:22-alpine`), `:16` (`python:3.12-slim-trixie`); `backend/Dockerfile.worker:8` (`mcr.microsoft.com/playwright/python:v1.61.0-noble`), `:9` + `Dockerfile.app:17` (`ghcr.io/astral-sh/uv:0.9.2` — version-pinned, matching CI's `uv 0.9.2`, which is the good pattern the others do not follow).
    - **Reproduction**: code read + `docker ps`/`docker inspect` on the live install (running containers resolve to floating tags); no digest appears anywhere in the repo (`grep '@sha256'` → none in compose/Dockerfiles).
    - **Root cause**: tags chosen for install simplicity; nothing pins or refreshes them, and there is no documented bump procedure.
    - **Proposed remedy category**: image pinning policy — pin digests (or at minimum patch-level tags) for the three compose images and the four base images, with a documented, testable bump path; note the Playwright image already proves the pattern (its tag must track the `playwright==` pin). Not implemented here.
    - **Source**: kickoff hunt list ("image and base-image pinning", "docs/config drift that could mislead an operator").
    - **Verified-clean contrast**: all GitHub Actions in `.github/workflows/*.yml` are SHA-pinned with version comments (including `actions/checkout@fbc6f399…`, `astral-sh/setup-uv@11f9893b…`), and `uv` is consistent between CI and both Dockerfiles.

    - **ID**: AUDIT-4E-6
    - **Title**: The Ollama default endpoint is a Docker-only constant with a self-contradicting fallback chain, so the auto-provisioned provider is *enabled* yet unresolvable on every default install while the module comment claims bare-host installs use localhost
    - **Severity**: **Low** — drift that misleads an operator/developer but degrades visibly and safely (Medium would be arguable for bare-metal installs, where the documented default can never resolve). No incorrect system behavior: with zero task assignments the escalation returns "not configured", and the UI surfaces the unresolvable host as a 422.
    - **Subsystem / file(s)**: `backend/app/ai_ollama.py:28-46` (`DEFAULT_OLLAMA_BASE_URL = "http://ollama:11434"`, `normalize_base`), `backend/app/ai_migration.py:124-151` (`seed_default_ollama_provider`, `validate_url=False`), `backend/app/llm.py:128-141` (`_litellm_api_base`, second copy of the same rule), `docker-compose.yml:155-162` (the `ollama` service is behind `profiles: ["ollama"]`), `.env.example:39-48` (documents only the Docker instruction).
    - **Reproduction**: live attestation — seeded `Ollama (local)` row is `enabled=t`, `base_url=http://ollama:11434`, `validation_status=unknown`; the `ollama` container is not running; `socket.getaddrinfo('ollama')` **fails** inside `wardress-app-1` (`gaierror -5`), so `GET /api/settings/ai/providers/{id}/ollama-models` answers 422 "Could not resolve host". Hermetic: `test_normalize_base_falls_back_to_the_docker_hostname` pins the three spellings — `None` and `""` → `http://ollama:11434`, `"   "` → `http://localhost:11434` (the comment's bare-host claim is true only for the whitespace spelling and false for the two normal ones); `test_validate_base_url_refuses_the_seeded_default_on_a_bare_host` pins that the same validator refuses an unresolvable host for `ollama` while allowing private IPs only for the two local types.
    - **Root cause**: one constant serves two deployment modes; the "default endpoint" rule is duplicated across `normalize_base`, `_litellm_api_base` and the seed, and the seed bypasses validation (necessarily) without recording that it chose a Docker-only value.
    - **Proposed remedy category**: config single-sourcing — one helper + one constant for the default endpoint (resolved per deployment mode or made explicit as Docker-only), plus aligning the seed's value and every comment with it. Not implemented here.
    - **Source**: kickoff hunt list ("auto-provisioned Ollama fallback correctness — what happens when the container is absent"); Rule 13 docstring-vs-reality pattern (cf. AUDIT-4D-4).

    - **ID**: AUDIT-4E-7
    - **Title**: The Ollama model-pull stream has no deadline of any kind (total or idle)
    - **Severity**: **Low** — the design is deliberate and documented ("a pull can take minutes; rely on the stream, not a deadline") and only an admin can start one, but a stalled daemon or a blackholing proxy holds the SSE response open indefinitely: there is no idle-progress watchdog, no max duration, and the request costs two rate-limit tokens for a call that may never finish.
    - **Subsystem / file(s)**: `backend/app/ai_ollama.py:25-26,114-139` (`_PULL_TIMEOUT = None`; `httpx.AsyncClient(timeout=None)`), `backend/app/routers/settings.py:855-915` (SSE endpoint, `enforce_user_rate_limit`).
    - **Reproduction**: hermetic, committed-passing — `test_ollama_pull_client_has_no_deadline` records the constructed client kwargs (`timeout=None`) while the two discovery calls pin `_DISCOVERY_TIMEOUT == 15`.
    - **Root cause**: "a pull is long" was implemented as "no timeout at all", conflating a long total duration with an absence of liveness signals.
    - **Proposed remedy category**: idle/stall timeout plus a generous max-duration cap (keep the stream semantics). Not implemented here.
    - **Source**: kickoff hunt list ("timeout budgets … retry storms"); cold read of `ai_ollama.py`.

    - **ID**: AUDIT-4E-8
    - **Title**: Provider-error redaction is heuristic (vendor prefixes + ≥32-char opaque runs), so a short custom-endpoint key echoed by a provider error survives into the log line and into the persisted `validation_detail`
    - **Severity**: **Medium** — a partial implementation that does not meet the redactor's stated intent ("scrub before writing [to] persistent logs / SIEM / support tickets") rather than a cosmetic nit: it requires the provider to echo the key (common: OpenAI-style "Incorrect API key provided: …") **and** a key shorter than 32 characters (only possible for a custom `openai_compatible` endpoint or an unusually short vendor key); the leak reaches server logs and the admin-visible `ai_providers.validation_detail`, not any unauthenticated surface. Graded Medium over Low because the exposure target is a credential and the fix is trivial; not High/Critical because it leaks nothing the admin cannot already read and the at-rest design is sound.
    - **Subsystem / file(s)**: `backend/app/llm.py:60-79` (`_SECRET_PATTERNS`, `_scrub_secrets`), `:199-202` (log line), `:389-390` (`validate_provider_call` detail), `backend/app/routers/settings.py:759-760` (persists `validation_detail[:500]`, returned in `AiProviderOut`).
    - **Reproduction**: hermetic, committed-passing — `test_scrub_only_catches_prefix_or_length_shaped_secrets`: `_scrub_secrets("Incorrect API key provided: shorty123")` is returned **unchanged**, while `sk-…` and `AIza…` shapes are replaced with `[REDACTED]`.
    - **Root cause**: the redactor only knows *shapes*; it never knows the actual secrets the process is handling (the configured keys live encrypted, so a value-based redaction was not wired).
    - **Proposed remedy category**: value-aware redaction — at log/response time, replace the provider's own configured key values (and their first/last few characters) in addition to the pattern heuristics. Not implemented here.
    - **Source**: kickoff hunt list ("any place a key could be persisted or logged in plaintext").

    - **ID**: AUDIT-4E-9
    - **Title**: Dependency-hygiene residue re-confirmed (AUDIT-2B-6): `aiosqlite==0.22.1` is an unused dev dependency and `scikit-learn==1.9.0` is a *runtime* pin whose only importer is a build-time tool
    - **Severity**: **Low** — no runtime impact; it is unused surface in the lockfile, the audit scope and (for scikit-learn) both shipped images.
    - **Subsystem / file(s)**: `backend/pyproject.toml:35` (`scikit-learn==1.9.0` in `[project] dependencies`), `:70` (`aiosqlite==0.22.1` in the dev group), `backend/tools/refit_fusion_model.py:46,367,445` (the only `sklearn` importer).
    - **Reproduction**: repo-wide grep for `aiosqlite` → no import anywhere (only a `models.py:11` comment; `tests/test_phase41_docs_sync.py:51` even asserts its absence from the docs text); grep for `sklearn` → only `tools/refit_fusion_model.py`. Both images install the runtime pin (`uv sync --frozen --no-dev`).
    - **Root cause**: AUDIT-2B-6's original diagnosis stands — a dev-time-only dependency declared in the runtime table (so it ships and is audited as runtime surface) and a harness dependency that outlived the SQLite harness.
    - **Proposed remedy category**: dependency hygiene — move `scikit-learn` to the dev group, drop `aiosqlite`, regenerate `uv.lock`. Not implemented here.
    - **Source**: AUDIT-2B-6 (carried lead), re-verified cold this phase.

    - **ID**: AUDIT-4E-10
    - **Title**: Two moderate frontend dev-dependency advisories sit just below the CI gate's severity threshold
    - **Severity**: **Low** — dev-only tooling (`vitest` / `@vitest/mocker` path-traversal advisory), CI's `pnpm audit --audit-level high` correctly passes (exit 0), so there is no gate failure; logged because "no known advisories" would be the wrong thing to record.
    - **Subsystem / file(s)**: `frontend/package.json:47` (`vitest ^4.1.10`), `frontend/pnpm-lock.yaml` (resolved `vitest@4.1.10`), `.github/workflows/ci.yml:143-144`.
    - **Reproduction**: `cd frontend; pnpm audit --audit-level high` → "2 vulnerabilities found / Severity: 2 moderate", exit 0; `pnpm audit --json` → advisories `1193683`/`1193684` (vitest, @vitest/mocker), patched `>=4.1.11`.
    - **Root cause**: dev dependency pinned one patch behind the fix; the gate is severity-based by design.
    - **Proposed remedy category**: routine dev-dependency bump to ≥ 4.1.11 on the next refresh (optionally separate dev/prod audit levels). Not implemented here.
    - **Source**: kickoff hunt list ("Vulnerability sweep … state the method and its limits honestly").

    - **ID**: AUDIT-4E-11
    - **Title**: The backend CI job cannot report success at HEAD — `ruff format --check .` fails on 24 files, and because it sits inside the same `run: |` step *before* the dependency audit and the test suite, those later gates never execute
    - **Severity**: **Medium** — rubric clause "a docs/infra drift that could mislead an operator but doesn't cause incorrect system behavior". Disclosed High argument for Phase 10: it is a true Gap between the workflow's documented intent ("`|| true` is NOT used — a known vulnerability fails CI and must be triaged"; the job exists to gate merges) and its actual behavior, and its concrete harm is *signal masking* — the first failing command aborts the step, so AUDIT-4E-4's Critical advisory is structurally unable to surface; three of the 24 offenders are this audit's own test files (Phases 4, 4B, 4D), i.e. the effort's own "suites are green" reports were true and its "CI is green" implication was not.
    - **Subsystem / file(s)**: `.github/workflows/ci.yml:56-72` (one `run: |` block: `ruff check .`, then `ruff format --check .`, then the separately-stepped `pip-audit`, `check_torch_osv.py`, `pytest` — the `|` block aborts at the second command); offenders include production capture files edited during PROMPT-002 (`worker/fetcher.py`, `worker/banner_dismiss.py`, `worker/page_prepare.py`, `worker/detection/dom.py`, `worker/detection/normalize.py`) and audit test files (`tests/test_phase4_fresh_eyes_finding_repros.py`, `tests/test_phase4b_orchestration_repros.py`, `tests/test_phase4d_delivery_repros.py`), plus 16 further files.
    - **Reproduction**: `cd backend; .venv\Scripts\python.exe -m ruff format --check .` → exit 1, "24 files would be reformatted, 168 files already formatted"; `ruff --version` = `0.15.21` and `pyproject.toml` pins `ruff==0.15.21`, so this is not a formatter-version surprise — the diffs are current-style reflows (a wrapped string/call that now fits the 100-col width collapsed to one line, blank-line runs normalized from two to one) that `ruff format` would apply silently. The history check confirms the pin has been `ruff==0.15.21` since Phase 0 (`git log -S 'ruff==0.15.21' -- backend/pyproject.toml` → `fe9d653` only), while the FIXLOG records the format gate as green at a later phase (:2764, "158 files already formatted") — i.e. the drift accumulated from hand-edits made after that pass rather than from a tooling change.
    - **Root cause**: the repo convention is "the formatter is the source of truth" but nothing enforces it at write time (no pre-commit hook and no editor/CI feedback on `ruff format`), and the offending files were produced by phases whose own verification step ran `ruff check` only — including this audit's Phases 4/4B/4D, whose log entries record `ruff check` passing (true) without a corresponding format check.
    - **Proposed remedy category**: infrastructure hygiene — split the CI lint into two steps (or `continue-on-error: false` per command) so a format failure cannot mask the audit/test steps, run `ruff format .` once across the tree (formatter-as-source-of-truth, AST-preserving per the FIXLOG's own risk note), and add the format check to whatever pre-commit/`build` path contributors actually run. Not implemented here (Rule 1 — and reformatting 24 files is a repair).
    - **Source**: kickoff hunt list ("dependency/config drift that could mislead an operator"; "confirm check_torch_osv.py … can actually fail the build" — extended to ask whether the job can *report* at all).

    - **Verified-clean addition (CI gate status measured, not inferred)**: the frontend job's lint gate passes (`pnpm lint` → oxlint, **0 errors**, 13 warnings, 77 ms, 76 files) and its audit gate passes (AUDIT-4E-10). The frontend test gate was deliberately **not** re-run here — `frontend/tests/capture-health.test.tsx`'s known flake is Audit Phase 4F's named root-cause target, and re-running it would consume that phase's evidence window. The backend job's status is AUDIT-4E-11.

- **Verified-clean ledger (fresh-eyes, evidence per item — Rule 13: re-verified against live behavior, not the docstrings)**:
    - **Fernet-at-rest on every credential write path** — VERIFIED. Only two `credentials_encrypted=` assignment sites exist in the whole backend (`app/ai_config.py:130` `create_provider`, `:160` `update_provider`), both through `encrypt_keys` → `crypto.encrypt_json` → Fernet; every AI router path (legacy Gemini single-key/pool add/remove, legacy Ollama, unified `POST/PATCH /api/settings/ai/providers`) funnels through those two functions. Hermetic proof: `test_every_ai_provider_write_path_stores_fernet_ciphertext` (ciphertext ≠ plaintext, round-trips, `provider_out` contains no secret, rotation replaces rather than appends), plus the pre-existing `test_phase5_audit.py::test_settings_update_records_no_secret` and `test_agent.py::test_agent_provider_redacts_keys`.
    - **Key material never leaves the backend** — VERIFIED. `provider_out` returns `key_hints` only (`ai_config.key_hints` → `llm._key_hint`), audit snapshots record counts/booleans (`key_count`, `keys_changed`), and `decrypt_provider_blob` is documented "migration/debug only". Redaction caveat is AUDIT-4E-8, not a leak of the at-rest design.
    - **`crypto.py` refuses to be guessable** — VERIFIED. `config.py`'s validators reject a `CREDENTIALS_ENCRYPTION_KEY`/`JWT_SECRET` under 32 bytes at startup, and a wrong/rotated key surfaces as `DecryptionError` which callers degrade on (`_keys_unreadable` → UI re-save prompt) rather than crashing a scan.
    - **Detection's second opinion can never blind the engine** — VERIFIED (the §0/§8 contract). `should_escalate` requires `changed and 0.40 <= risk < 0.75`; the block is skipped when already `flagged`; `escalation_upgrades_verdict` only returns True for a confident `defacement` (≥ 0.6), so the LLM can only raise attention; `parse_classification` rejects non-JSON/mis-classified/unparseable replies (None → "unparseable reply" evidence); `escalate_scan` catches `LLMUnavailable` and bare `Exception` and converts both to evidence strings; the block is `await`ed as a plain coroutine, so no Celery retry/backoff is involved and no exception can escape the scan (latency is AUDIT-4E-3).
    - **Retry/backoff storms** — VERIFIED as absent: `llm.py` sets `num_retries` on the Router only, there is no Celery `autoretry_for` anywhere in the AI path, `litellm.drop_params=True`/`telemetry=False`/`suppress_debug_info=True` are set once, and Router cooldown (`allowed_fails=0`, 60 s) prevents a hot-loop against a failing provider.
    - **Partial/garbage provider responses** — VERIFIED: `_MAX_OUTPUT_CHARS` truncation, `parse_classification`'s strict-JSON-first/non-greedy-fence fallback, `confidence` clamped to [0,1], `rationale` capped at 500 chars, and `validate_provider_call`'s `detail` capped at 500 chars before persisting.
    - **Startup resilience** — VERIFIED: `ai_startup.bootstrap_migration`/`bootstrap_catalog` swallow every exception with `logger.exception` and are documented "never raises"; `sync_catalog` never raises and its fallback ladder is live-consistent (live → keep existing rows → bundled snapshot → "none"); `upsert_catalog` refuses an empty model set ("Refusing to upsert an empty model catalog") so a malformed/empty live payload cannot wipe the catalog.
    - **Legacy migration & seeding idempotence** — VERIFIED: `migrate_legacy_ai_settings` no-ops once any provider exists and handles both legacy Gemini shapes (single `api_key` and the pool `keys:[…]`), preserving the old "Gemini wins explanation, Ollama never gets agent chat" preference; `seed_default_ollama_provider` is gated by the `ai_seed_done` sentinel *and* the "any provider exists" check, so a deliberately deleted provider is never resurrected — matching the live install (`ai_seed_done` present, exactly one seeded provider).
    - **The deprecated adapters write through the new tables** — VERIFIED: `/api/settings/gemini*`, `/api/settings/ollama*` read/write `ai_providers`/`ai_task_assignments` via the same service layer, so there is no second source of truth for credentials (legacy `app_settings` rows are no longer read as truth) — the only divergence is the missing save-time SSRF check (AUDIT-4E-1).
    - **`check_torch_osv.py` is wired into CI AND can fail the build** — VERIFIED cold, not from its docstring: `ci.yml:67-70` runs it as its own step with no `|| true`/`; true`; it is non-vacuous against the real lockfile (torch `2.13.0` + `2.13.0+cpu` present, local label stripped for the OSV query); the live run today exits **0** with "torch 2.13.0: no known advisories"; and its failure modes actually fail — `exit 1` on a synthetic advisory and `exit 2` when OSV is unreachable (fail-closed by design), pinned hermetically in 5 tests. `pip-audit`'s companion step is likewise un-swallowed, which is why AUDIT-4E-4 is a red gate rather than a hidden one.
    - **`.env.example` secrets handling** — VERIFIED: every secret is a `CHANGE_ME_…` placeholder; `install.ps1` generates values with a CSPRNG (rejection-sampled alphanumeric alphabet, works on PS 5.1 and 7+), writes LF/no-BOM, then **asserts no assignment line still contains `CHANGE_ME`** — deleting the file and failing hard if one survived; a pre-existing `.env` still containing placeholders is refused rather than trusted. `.env` is gitignored; `scripts/diagnostics.ps1` reports placeholder presence without printing secret values.
    - **No default credentials anywhere** — VERIFIED: `docker-compose.yml` uses `${POSTGRES_PASSWORD:?…}`/`${JWT_SECRET:?…}`/`${CREDENTIALS_ENCRYPTION_KEY:?…}` (compose refuses to start without them), `TELEGRAM_BOT_TOKEN` defaults empty (the bot is profile-gated and the alert channel requires a live `/start`), `ADMIN_PASSWORD` is empty by default with `app/seed_admin.py` enforcing `MIN_PASSWORD_LENGTH = 12`, and CI's placeholder secrets are job-scoped to throwaway service containers.
    - **CI hygiene** — VERIFIED: least-privilege `permissions: contents: read`, per-ref concurrency that never cancels `main`, SHA-pinned actions with version comments, a real-Postgres service with an alembic round-trip + `alembic check` drift gate, `pnpm install --frozen-lockfile` and `uv sync --frozen` on both sides, and pnpm/node/uv versions consistent with the Dockerfiles.
    - **Frontend/prod dependency posture** — VERIFIED: no production runtime advisories at any severity; the only findings are dev-tooling moderates (AUDIT-4E-10).
    - **`.env.example` ↔ `config.py` ↔ compose field agreement** — VERIFIED for every forwarded variable (rate limits, token TTLs, `MAX_REQUEST_BODY_BYTES`, `COOKIE_SECURE`, `CORS_ALLOWED_ORIGINS`, `TRUST_PROXY_HEADERS`), and the `ARTIFACTS_DIR` exclusion is documented in all three places rather than being a silent omission — the honest-documentation pattern this phase looked for.
    - **Bundled catalog snapshot integrity** — VERIFIED live: 1.53 MB / 172 providers / 5751 models in the compact shape `load_snapshot` expects, never rewritten at runtime (as documented), while the DB retains 7850 live models.
    - **Dockerfile hygiene** — VERIFIED: dependency layer before source copy, `uv sync --frozen --no-dev` in both images, MiniLM pre-baked into the worker image so a scan never needs HuggingFace at runtime, the Playwright tag deliberately tracked to the `playwright==1.61.0` pin (documented in three places), and every `apt-get install` ends with `rm -rf /var/lib/apt/lists/*`.

- **Log-vs-reality discrepancies**: none against PROMPT-002/PROMPT-003 log claims (re-verifying those was Phases 1-2's mandate). Two divergences were found and logged *in-phase* per Rule 13's docstring-vs-reality pattern: AUDIT-4E-2 (`app/ssrf.py`'s "Every URL the platform is asked to fetch goes through `assert_url_allowed`" is false for the catalog fetch) and AUDIT-4E-6 (`ai_ollama.py`'s own comment claims a bare host install uses localhost while the module's normal inputs resolve to the Docker hostname). One **self**-falsification is recorded in the method rather than hidden: my first-pass reading of `llm.py` implied `num_retries` would multiply network waits (≈90 s worst case); measurement refuted it (30 s for one deployment, 60 s for two), so AUDIT-4E-3 is written to measured behavior, not to the arithmetic. One minor docs drift of the phase spec itself: §4's 4E target list names a repository-root `frontend/package.json`/`pnpm-lock.yaml` pair as `pnpm-lock.yaml`, but no root lockfile exists — the two real ones are `frontend/pnpm-lock.yaml` and `walkthrough/pnpm-lock.yaml` (the walkthrough app is deployed by `.github/workflows/static.yml`, not by CI's frontend job), so "the project's dependency tree" is in fact two independent trees.

- **New hermetic tests added this phase**: `backend/tests/test_phase4e_ai_supplychain_repros.py` — **21 tests, all committed-passing** (Rule 5/10). Characterization tests: each asserts CURRENT behavior deterministically so the remediation prompt can flip the specific assertions it fixes.
    - SSRF-policy gap (AUDIT-4E-1): `test_legacy_put_ollama_create_branch_stores_unvalidated_base_url`, `test_validate_endpoint_never_consults_the_ssrf_policy`, `test_ollama_models_endpoint_does_consult_the_ssrf_policy` (control), `test_resolve_task_hands_unvalidated_base_url_to_litellm`.
    - Catalog fetch (AUDIT-4E-2): `test_fetch_live_catalog_never_consults_the_ssrf_policy`, `test_fetch_live_catalog_builds_an_unpinned_client`.
    - Hung-provider budget (AUDIT-4E-3): `test_router_configures_a_per_model_group_retry_budget`, `test_every_key_is_its_own_deployment_and_its_own_timeout`, `test_hung_deployment_degrades_after_one_timeout_budget` (local hang server, degenerate 0.4 s budget), `test_keyless_custom_endpoint_fails_fast_instead_of_hanging` (verified-clean).
    - Ollama default/deadline (AUDIT-4E-6/-7): `test_normalize_base_falls_back_to_the_docker_hostname`, `test_validate_base_url_refuses_the_seeded_default_on_a_bare_host`, `test_ollama_pull_client_has_no_deadline`.
    - Redaction (AUDIT-4E-8): `test_scrub_only_catches_prefix_or_length_shaped_secrets`.
    - Fernet positive proof: `test_every_ai_provider_write_path_stores_fernet_ciphertext`.
    - Supply-chain gates: `test_gate_is_wired_into_ci_without_a_swallowing_operator`, `test_torch_is_actually_present_in_the_audited_lockfile`, `test_advisory_makes_the_gate_exit_nonzero`, `test_unverifiable_osv_fails_closed`, `test_unreadable_lockfile_is_a_hard_error`, `test_lockfile_without_torch_is_a_pass`.
    - Scratch probes (**preserved for reproducibility** under `Prompts/Pending/Finders/PROMPT-003/scratch/`, per the effort's precedent — Rule 5/10: not pytest, not part of any suite): `probe_ai_llm_hang_budget.py`, `probe_ai_llm_hang_multikey.py`. No production file was modified (Rule 1).

- **Opportunities / Innovation ideas observed** (Rule 17 — not severity-scored, not gap-driven):
    - **Idea**: O-4E-1 — one shared outbound-fetch factory
    - **Why it would help**: AUDIT-4E-1, AUDIT-4E-2 and AUDIT-4D-3 are all the same defect (a call site that forgot the pinning transport / the policy), and each was found by a different phase. A single factory that always installs `SSRFPinningTransport` + a policy pre-check would make "forgot the policy" unrepresentable, and turn the `ssrf.py` docstring back into a fact rather than an aspiration.
    - **Where it touches**: `backend/app/ssrf_transport.py` (new helper), `ai_catalog.py`, `site_icons.py`, `ai_ollama.py`, `remediation.py`, `routers/imports.py`, `worker/probe.py`.
    - **Rough shape of the change**: a `safe_async_client(**kwargs)` that injects the pinning transport and validates on open, plus a small test asserting no module builds a bare `httpx.AsyncClient` for outbound work. Sketch only.
    - **Idea**: O-4E-2 — surface dependency-audit state on the health page
    - **Why it would help**: AUDIT-4E-4 is a red CI gate a self-hosted operator never sees unless they read GitHub Actions. "audit state: 1 known advisory (weasyprint 69.0 → 70.0)" next to the existing health indicators makes supply-chain status operator-visible, not CI-only.
    - **Where it touches**: `backend/app/routers/health.py` (+ optional `docs/`), mirroring the existing capture-health rollup pattern.
    - **Rough shape of the change**: persist the last audit result as a small JSON artifact (written by CI or a `backend/tools/` summary script) and render it as one health row; no runtime network call. Sketch only.
    - **Idea**: O-4E-3 — an AI-degradation rollup (escalation outcome counts)
    - **Why it would help**: the escalation's `status` already lands in layer-8 evidence ("ok" / "unavailable: …" / "unparseable reply") but nothing aggregates it; a counter over the last N scans would make a quietly-broken provider (bad key, quota, hung endpoint) visible as one number instead of only inside individual findings.
    - **Where it touches**: `worker/llm_escalation.py` (evidence already emitted), `app/routers/health.py`, `frontend/src/pages/health.tsx`.
    - **Rough shape of the change**: aggregate escalation statuses while loading scans for the health summary; render a small table. Pairs with O-4D-1's delivery rollup. Sketch only.
    - **Idea**: O-4E-4 — memoize the validated address set for the fixed catalog host
    - **Why it would help**: once the catalog fetch goes through the pinning transport (AUDIT-4E-2), the same constant URL is re-resolved at startup and on every beat tick; a per-process memo of the validated address set for `models.dev` keeps the check without paying DNS each refresh.
    - **Where it touches**: `backend/app/ai_catalog.py` (`fetch_live_catalog`).
    - **Rough shape of the change**: reuse the pattern the probe path already uses (validate once, connect to the validated literal within the client's lifetime). Sketch only.

- **Full regression results** (Windows host; Docker stack up and used read-only — wardress-app/worker/beat/db/redis + disposable wardress-test-pg on 127.0.0.1:5433; every pytest run against the alembic-migrated production-dialect schema, one session per database — Rule 13: every count below is from an actual run this session):
    - New repro file: `cd backend && uv run --frozen pytest tests/test_phase4e_ai_supplychain_repros.py -q -p no:cacheprovider` → **21 passed in 13.97 s** (0 failed, 0 skipped). Two intermediate failures were **my own** over-claiming assertions, corrected in-phase rather than papered over: the retry-multiplication arithmetic (refuted by measurement) and `normalize_base("   ")` (which really does return localhost, so the claim became AUDIT-4E-6's two-spelling divergence). Both are recorded above.
    - AI/SSRF/API regression batch: `uv run --frozen pytest tests/test_ai_catalog.py tests/test_ai_migration.py tests/test_llm_keypool.py tests/test_phase16_outbound_fetch.py tests/test_phase5_ratelimit_ssrf.py tests/test_ssrf.py tests/test_phase4c_api_surface_repros.py tests/test_phase4_api.py tests/test_phase5_audit.py tests/test_phase5_rbac.py tests/test_phase4e_ai_supplychain_repros.py -q` → **194 passed, 1 warning in 99.24 s** (the warning is a pre-existing apprise `imghdr` DeprecationWarning). 0 failed, 0 skipped.
    - Lint/format on the new file: `ruff check tests/test_phase4e_ai_supplychain_repros.py` → **All checks passed!**; `ruff format --check` on it → **already formatted** (one E501 and one format pass fixed before commit, both self-inflicted).
    - Supply-chain gates executed live: `tools/check_torch_osv.py` → exit **0**, "torch 2.13.0: no known advisories"; `pip-audit --skip-editable` → exit **1**, "Found 1 known vulnerability in 1 package" (weasyprint 69.0 → 70.0) — AUDIT-4E-4; `pnpm audit --audit-level high` → exit **0** (2 moderate, dev-only); `pnpm lint` → exit **0** (0 errors / 13 warnings).
    - Repository-wide format gate (not a suite, but a CI gate): `ruff format --check .` → exit **1**, 24 files — AUDIT-4E-11.
    - No production file was modified (Rule 1); the live stack was used read-only; no install/uninstall script was run.

- **Findings out of phase scope** (logged for the correct future phase, not investigated here):
    - The unformatted production files AUDIT-4E-11 lists (`worker/fetcher.py`, `worker/banner_dismiss.py`, `worker/page_prepare.py`, `worker/detection/dom.py`, `worker/detection/normalize.py`, …) are cosmetic-only; their *contents* belong to the capture/detection remediation prompt (AUDIT-3-*/AUDIT-4-*), not to this phase.
    - `frontend/tests/capture-health.test.tsx`'s flake and the frontend's verdict/severity color clarity are Audit Phase 4F's named targets; the frontend test gate was deliberately left un-run here (see the gate-status note above).
    - `app/routers/reports.py`'s WeasyPrint call shape was checked only for advisory reachability; the report renderer's full surface (thread offload, error mapping, template contract) stays with 4C/4D.
    - `worker/telegram_bot.py` consumes `CREDENTIALS_ENCRYPTION_KEY` and the shared alerting helpers; its own transport surface remains excluded per §0.
    - The models.dev catalog's *data* trust model (is a third party's model metadata trusted enough to drive provider UX?) is a design question for the remediation prompt / PROMPT-004, not a defect found here.

- **Commit**: `e100045` — test(audit-4e): AI provider integration & supply-chain repro tests (diagnosis only); this log entry is committed immediately after, referencing that hash (not pushed).
- **Next phase kickoff prompt**: delivered in chat only — never written to this log.

### [DONE] PROMPT-003 Audit Phase 4F — Fresh-Eyes Code Audit: Frontend Capture & Detection Surfaces

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-19
- **Assigned subsystem** (per the Phase 2B inventory, bucket 6 — 34 src + 21 test files, the authoritative list, not §4's short list): pages `health.tsx`, `site-detail.tsx`, `scan-detail.tsx`, `alerts.tsx`, `remediation.tsx`, `sites.tsx`, `settings.tsx`, `audit.tsx`, `assistant.tsx`, `login.tsx`, `App.tsx`, `main.tsx`; components `finding-card.tsx`, `dom-diff-tree.tsx`, `risk-gauge.tsx`, `incident-timeline.tsx`, `visual-diff-slider.tsx`, `suppression-panel.tsx`, `remediation-hooks-panel.tsx`, `status-dot.tsx`, `site-favicon.tsx`, `site-avatar.tsx`, `ai-settings-card.tsx`, `users-card.tsx`, `ui/*` primitives; lib `api.ts`, `auth.tsx`, `use-artifact.ts`, `use-site-icon.ts`, `use-reduced-motion.ts`, `site-icon-state.ts`, `site-avatar.ts`, `bbox.ts`, `listbox-keys.ts`, `numeric-inputs.ts`, `utils.ts`; and all of `frontend/tests/*`. Caller/callee tracing reached `app/scanning.py`, `worker/scan_tasks.py`, `worker/detection/{types,pipeline,fusion}.py`, `app/routers/{sites,health}.py` and `worker/beat_tasks.py` on the backend side (constant provenance, payload shapes, drift guards).
- **Environment & parity (Rule 13)**: **the user rebuilt the stack mid-phase** (`scripts/update.ps1`) — `wardress-app-1` is now built from HEAD: `/app/static/assets/index-*.js` timestamps moved to 2026-09-19 06:00 and the bundle now contains HEAD's Phase-7 markers ("Capture Quality (24h)", "no capture evidence yet", "Capture method updated"). This **closes AUDIT-4B-8's precondition** (deployed frontend predating HEAD). **No prior phase is invalidated or needs rework**: 4B detected the mixed build, logged it as a finding, and explicitly refused to treat live rendering as HEAD-valid ("the hash diff above is the authoritative parity statement"); 4C/4D/4E `docker cp` + `git hash-object`-verified every audited file before asserting; 4B/4C's live-probe conclusions were qualified at the time they were written. Nothing in this phase's findings depends on pre-update container state — every finding is source-level and the flake investigation is host-side (vitest, not the container). Live state re-attested post-update: app/worker/beat/db/redis + disposable `wardress-test-pg` on 127.0.0.1:5433 all up, `wardress-app-1` healthy on :8321. No install/uninstall script was run by this agent.
- **Method (cold, §2 Step 3)**: full cold read of the in-scope files and their seams. Gates were **measured, not assumed** (AUDIT-4E-11's lesson): `pnpm lint` → exit 0 (0 errors / 13 pre-existing `react/only-export-components` warnings); `pnpm exec tsc -b` → exit 0; full suite `pnpm exec vitest run` → **22 files / 144 tests / 0 failed, exit 0, three consecutive passes** (12.8 / 13.1 / 12.4 s). Flake protocol per Rule 18/19: 45 passes of `capture-health.test.tsx` across three load conditions, an in-process 25-mount latency series, a *measured* assertion budget, and a deterministic repro (all three probe scripts + their result logs preserved in `Prompts/Pending/Finders/PROMPT-003/scratch/`). Scratch instrumentation test files were deleted before commit (documented below). No production file was modified (Rule 1).

- **Verified-clean areas (Rule 13 — what was checked and found sound, not only what broke)**:
  - **No state leakage between tests** (the phase's explicit flake hypothesis): 25 sequential `SiteDetailPage` mounts inside *one* test body all resolved (fresh `QueryClient` per test + per-test stub/unstub; the only module-level mutable state, `activeRebaselines`, is touched by neither flaky test).
  - **Rule 12 sweep — no Critical fired**: every client URL is a *relative same-origin* path built from server-provided ids (`/api/sites/{id}/icon`, `/api/artifacts/baselines/{id}/screenshot`); there is no env-overridable base URL, no user- or hostname-derived URL construction anywhere in `src/`; the access token lives in module memory only (never `localStorage`), refresh is single-flight across the 401-retry *and* the boot-time silent refresh (`api.test.ts` 8/8 green), and `artifactFetch`/`useSiteIcon` route through the same refresh. CSRF/credential handling in the client is sound.
  - **Optimistic updates**: the only one is `activeRebaselines` (add on `onMutate`, remove on `onError`/settled status) — correct and self-healing. Alerts/remediation/suppression mutations invalidate rather than write optimistically.
  - **`queryKey` scope**: `["sites", id, "scans", { page }]`, `["sites", id, "scans", "timeline"]`, `["sites", id, "scans", scanId]` are distinct record keys — no collision, and `invalidateQueries(["sites", id, "scans"])` covers all three by prefix. No stale-after-mutation case found (AUDIT-4F-9 is a redundant-fetch issue, not staleness).
  - **XSS/inertness**: captured HTML is parsed through `DOMParser` into inert documents and rendered as text; hostile-fixture coverage already exists (`evidence-rendering.test.tsx`, `dom-diff.test.tsx`), both re-ran green. `sanitizeApiDetail` strips internal-looking server detail. Long error/URL text uses CSS `truncate`, so the full string stays in the DOM (screen-reader-safe).
  - **Status-colour contrast**: token values (`#11ff99` / `#ff801f` / `#ff2047` on `#000000`–`#0a0a0c`) are high-contrast; `StatusDot` is `aria-hidden` and always paired with a text label. The colour *system* is the problem (AUDIT-4F-4), not the palette.
  - **AUDIT-4B-5 lead (stalled-scheduler honesty)**: the Beat card is honest — badge `stale` + `last dispatch: never` when the heartbeat key is absent, `Xm ago` otherwise (5 min threshold vs `DISPATCH_TICK_SECONDS = 60`, `HEARTBEAT_TTL_SECONDS = 600`), and the telemetry pane shows the raw `last_tick`. The topology node word is the generic `degraded` (system vocabulary) rather than "no heartbeat" — the only clarity residue, folded into AUDIT-4F-4's remedy class. Its two hard-coded `60s` strings currently agree with `beat_tasks.py:46` (now guarded; see AUDIT-4F-5).
  - **No cross-scan staleness**: `scan-detail` stops polling once a scan is terminal and terminal rows are immutable server-side, so "a completed scan rendering over a newer one" is not reachable on that surface; the list/detail pages poll only while rows are `pending`/`running`.
- **Findings**:

    - **ID**: AUDIT-4F-1
    - **Title**: `capture-health.test.tsx`'s flake is an *implicit 1000 ms assertion budget* against a data path whose render cost spans ~35x — root-caused, not a race, not test-state leakage
    - **Severity**: **Low** — justified: no product behaviour is affected and the suite has never produced a false *green*; the defect is in the verification gate itself (a false red at load, whose practical consequence is exactly the Rule 19 anti-pattern of "re-run until green"). It is root-caused here, not re-run, and is offered to the remediation prompt as a test-hardening item (Fix-candidate).
    - **Subsystem / file(s)**: `frontend/tests/capture-health.test.tsx` (the two `site detail` tests); the awaited components are `src/pages/site-detail.tsx` (+ its `useArtifact`/`SiteFavicon` fetches) and `src/pages/health.tsx`. Harness: `@testing-library/react` `waitFor` default 1000 ms; `vite.config.ts` sets no `testTimeout` (vitest default 5000 ms — 5x head-room, so the failure surfaces as an assertion error, not a test timeout).
    - **Reproduction**: (a) committed deterministic repro — `frontend/tests/phase4f-capture-surface-repros.test.tsx::AUDIT-4F-1`: with a *correct* payload arriving 1400 ms late the extant assertion shape throws at 1016–1020 ms (`expected 'Loading…' to contain 'Example'`), while the byte-identical payload with `{ timeout: 6000 }` passes. (b) 45 passes of the target file across three conditions: 15 isolated (all green; `site-detail` test 4 durations **21 / 22 / 22 / 22 / 23 / 23 / 23 / 24 / 25 / 25 / 27 / 32 / 33 / 409 / 514 ms**, test 3 51–114 ms, health test 1 152–294 ms, wall 4.0–4.8 s, cold 13.3 s), 3 full-suite passes (green, file tests 73–187 ms), 20 concurrent isolated passes at K=5 (20/20 green). **Variance statement: zero failures in 45 passes under any condition** — the historical one-shot flake did not reproduce at this load; what reproduces on demand is the mechanism, at a 1400 ms delay.
    - **Root cause**: the awaited text is committed only after *five* requests settle on mount (`/api/sites/{id}`, `…/scans?offset=0&limit=20`, `…/scans?offset=0&limit=200`, `/api/sites/{id}/icon`, `/api/artifacts/baselines/{id}/screenshot` — call sets were identical on all 25 instrumented mounts), and the suite waits for it with the 1000 ms default budget. Per-mount cost is bimodal: ~22 ms warm, but the *first* mount in a process pays React+TanStack+recharts lazy-chunk warm-up (83 / 340–372 ms observed), and any scheduling hiccup pushes the whole path past 1000 ms. It is **not** fake timers, async `act`, MSW (the file stubs `fetch` directly), cross-test leakage (see the verified-clean list), or a wrong payload.
    - **Proposed remedy category**: test hardening (no production change) — an explicit `timeout` on the payload-dependent `waitFor`s (or one `configure({ asyncUtilTimeout })` in a setup file), and/or asserting on a state reachable without waiting for all five fetches.
    - **Source**: Gauntlet Step 5 (repeatability) + Rule 18 — the phase's mandated flake hunt.


- **ID**: AUDIT-4F-2
    - **Title**: A scan whose detection channels went **dark** renders with the same vocabulary as a measured-identical scan — the API's structured `degraded` flag is dropped by the client, and the two surfaces that can see it contradict each other
    - **Severity**: **Medium** — justified: PROMPT-002 Phase 7's own intent is explicit ("the degraded flag is what the *site-detail* and health aggregates key on to surface systematic capture failures", `worker/scan_tasks.py:169-172`) and only the health aggregate honours it — a partial implementation of documented intent (§6.4 Medium), not a cosmetic nit. **Not** Critical/High: the fused score itself is honest (a dark channel contributes *uncertainty*, never a fake 0.0 — `fusion.py:188-192`), no alert path is affected, nothing is lost, and the fleet-level counter does expose the condition; but an operator drilling into the site sees `Clean` / green dot / `0%` for a scan that measured nothing on some layers, while the Health page simultaneously counts that site under "Degraded Captures (24h)".
    - **Subsystem / file(s)**: `src/lib/api.ts:312` (`layer_scores: Record<string, { score: number | null; skipped: boolean }>` — the third key is missing), `src/pages/site-detail.tsx:71-101` (`verdictBadge`/`scanDot`/`riskCell`), `:103-110` (`layerSummary` conflates "structurally gated skip (proof of zero)" with "degraded (dark channel)"), `:436`, `:718-773`; backend seams: `worker/detection/types.py::degraded_result` (`score None, skipped True, degraded True`), `worker/scan_tasks.py:161-180`, `app/routers/sites.py:70-90` (`_has_degraded_layer`) and `:231` (`consecutive_degraded_scans`).
    - **Reproduction**: committed — `phase4f-capture-surface-repros.test.tsx::AUDIT-4F-2`: a completed scan with `verdict "clean"`, `risk_score 0`, `layer_scores.layer1_hash = {score: null, skipped: true, degraded: true}` (the authoritative `degraded_result` shape) and `consecutive_degraded_scans: 4` on the site payload renders **`Clean` / `0%` / `0/1 layers ran`**, and the string "degraded" appears nowhere on the page. A second test pins the contract gap from both ends: the worker emits `score/skipped/degraded` while `api.ts` declares only `score/skipped`, and `consecutive_degraded_scans` is referenced by **zero** files under `src/` (measured), i.e. it is not even declared as a type.
    - **Root cause**: the client contract was narrowed when `layer_scores` was typed, so no component *can* key on the flag without a type change, and the per-site streak was never added to the `Site` type. The UI therefore infers health from `verdict`/`risk_score` alone, which cannot distinguish "measured identical" from "not measured".
    - **Proposed remedy category**: contract completion + presentation (add `degraded?: boolean` to the `layer_scores` type; declare and render `consecutive_degraded_scans`; introduce a distinct third state — degraded/partial — on badge, dot and layer summary). Pairs with AUDIT-4's Lead 1 (findings rows carry no `degraded` column) — the scan payload already carries enough to fix the list without a schema change.
    - **Source**: Gauntlet Step 3/4 (cold read + adversarial payload shapes) — the phase's mandated "degraded vs measured" colour/clarity hunt.

    - **ID**: AUDIT-4F-3
    - **Title**: An unexpected 200 response shape blanks the entire dashboard — no shape guard at the client boundary and no error boundary anywhere
    - **Severity**: **Medium** — justified honestly: reachable through version skew (a long-lived SPA tab against a newer API is the *proven* condition in this deployment — AUDIT-4B-8), impact is a blank screen with no message and no recovery short of a manual reload, and React's own runtime warning names the missing remedy. Not Critical (no false-clean, no data loss, no server-side blast radius) and not High (it requires a contract violation rather than load or hostile input).
    - **Subsystem / file(s)**: `src/pages/site-detail.tsx:338`, `:351` (both `refetchInterval` callbacks) and `:436` (render-time `scanInFlight`) — `query.state.data?.items.some(...)` guards `data`, never `items`; `src/App.tsx` / `src/main.tsx` — no `componentDidCatch`, no `getDerivedStateFromError`, no `errorElement` anywhere in `src/` (grepped: zero hits).
    - **Reproduction**: committed — `phase4f-capture-surface-repros.test.tsx::AUDIT-4F-9`: stub `GET …/scans?offset=0&limit=20` with a **200** body `{total: 1, offset: 0, limit: 20}` (no `items`); the page renders, then tears itself down to an empty container (`innerHTML === ""`), with the escaping error captured verbatim as `Cannot read properties of undefined (reading 'some')`. During the full-suite passes React printed its own confirmation on stderr: *"An error occurred in the `<SiteDetailPage>` component. Consider adding an error boundary to your tree to customize error handling behavior."*
    - **Root cause**: the client trusts response shapes it never validates, and the throwing expression sits inside a React Query observer callback (and in render), so it escapes React's normal error path; with no boundary at the root, React unmounts the whole tree.
    - **Proposed remedy category**: boundary hardening — one root error boundary (rendering a "data contract mismatch / reload" state instead of a blank page) plus a shape validator for the paged payloads (`items`/`total`) at the `api()` boundary.
    - **Source**: Gauntlet Step 4 ("what if a 200 is not the shape we expect?").
- **ID**: AUDIT-4F-4
    - **Title**: Severity colour is defined five different ways across the capture surfaces, and the per-layer tone ignores the site's own `flag_threshold`
    - **Severity**: **Low** — justified: the *primary* verdict signals are threshold-correct (`verdictBadge` is verdict-driven; `RiskGauge` and `IncidentTimeline` take the site threshold; `riskCell` is verdict-driven), every tone is accompanied by a text label, and no reading is silently inverted for a *measured* value. What is wrong is consistency: the same number can read orange on one surface and red on another, and the per-layer helpers answer a different question than the rest of the app.
    - **Subsystem / file(s)** — the five definitions (+2 colliding ones):
      1. `src/components/risk-gauge.tsx:17-21` — `riskTone(risk, threshold)` → **threshold-aware** (`>= threshold` red, `>= 0.15` orange);
      2. `src/components/finding-card.tsx:42-55` — `scoreTone` / `dotFor` → **hardwired 0.5 / 0.15**, no threshold parameter (also `FindingCard:628` "signaled" = `>= 0.15`, and the fusion bar at `:597-605`);
      3. `src/pages/scan-detail.tsx:453-464` — the active-layer risk pill → **hardwired 0.5 / 0.15**;
      4. `src/components/incident-timeline.tsx:135-143` — the reference line at the **site** threshold;
      5. `src/pages/site-detail.tsx:91-101` — `riskCell` → **verdict-driven**;
      plus `alerts.tsx:167` / `remediation.tsx:161` (unconditional red — AUDIT-4F-8) and `dom-diff-tree.tsx:172-183` (accent-**green** = "added" content, the same green that means *clean* everywhere else, while the visual-diff slider paints altered regions accent-**red** for the same comparison). Layer-summary hit threshold `0.05` (`site-detail.tsx:108`) is a sixth, undocumented tier.
    - **Reproduction**: committed — `phase4f-capture-surface-repros.test.tsx::AUDIT-4F-4`: `scoreTone(0.45) === "text-accent-orange"` while `riskTone(0.45, 0.3) === "red"` and `riskTone(0.45, 0.5) === "orange"` — one value, three tones; plus a source guard showing `scoreTone` has no threshold input.
    - **Root cause**: no shared severity module. Each surface re-derived its own bar, and the per-layer helpers were written for a *global* default (the 0.5 default `flag_threshold`) rather than for the site being viewed, so a site configured at 0.3 shows a flagged scan whose layers read green/orange.
    - **Proposed remedy category**: consolidation — one exported tier helper (`riskTone(value, threshold)`) and one constants module, adopted by all seven call sites; make the layer/fusion tone threshold-aware and give the DOM-diff legend its own neutral vocabulary instead of the app-wide clean/dirty accents.
    - **Source**: Gauntlet Step 3/4 — the phase's mandated "verdict/severity colour clarity" hunt.

    - **ID**: AUDIT-4F-5
    - **Title**: `risk-gauge.tsx:19` asserts a constant that has moved — **AUDIT-2B-5 CONFIRMED against current code, extended to the same class elsewhere, and closed into an executable guard**
    - **Severity**: **Low** (comment-only drift that misleads any reader of the component; it does not change behaviour).
    - **Subsystem / file(s)**: `src/components/risk-gauge.tsx:19` — `if (risk >= 0.15) return "orange" // the scheduler's material-change band`; the material-change band is `MATERIAL_CHANGE_RISK = 0.40` (`backend/app/scanning.py:58`) and the LLM escalation floor is also `0.40` (`worker/llm_escalation.py:37`). 0.15 is **not** any backend constant (grepped `app/` + `worker/`: the only 0.15s are `cloaking.py::_ADD_RAMP_LO`, `metadata.py:272`, a visual-diff operating-point comment, and the `scanning.py:48` prose "churn … fuse to ~0.14-0.15") — it is the frontend's own tone bar, so the comment invents a provenance it never had.
    - **Extension of the class (same defect shape, found by sweeping for it)**:
      - `worker/detection/fusion.py:40` and `:192` both assert "the material-change bar / escalation floor (both **0.35**)" while the same file's own rule-floor table uses **0.40** (`:185`) and both named constants are 0.40 — three statements disagreeing inside one file. Routed to the detection remediation scope (see "out of phase scope"), recorded here as evidence the class is repo-wide.
      - `src/pages/health.tsx:308` / `:987` hard-code the beat tick as `60s`, duplicating `DISPATCH_TICK_SECONDS = 60` (`worker/beat_tasks.py:46`) with no shared source — **verified in agreement today**, now guarded.
    - **Reproduction**: committed — `phase4f-capture-surface-repros.test.tsx::AUDIT-4F-5` (two tests): one parses the gauge's tier and its comment, parses `MATERIAL_CHANGE_RISK` out of `scanning.py`, and asserts `0.15 != 0.40` while the comment still claims the band; the other cross-checks `health.tsx`'s `60s` against `DISPATCH_TICK_SECONDS`.
    - **Root cause**: comments and literals are free-standing copies of values that live in (and move in) other layers, with nothing that fails when they diverge.
    - **Proposed remedy category**: docs/code drift — fix the comment (or delete the tier bar in favour of the threshold-aware helper from AUDIT-4F-4, leaving the comment nothing to assert); keep the new guards as the standing check — **O-8 delivered as a test** rather than as a script.
    - **Source**: prior-history sweep (AUDIT-2B-5 / O-8) + cold re-verification against current code.
- **ID**: AUDIT-4F-6
    - **Title**: Mixed-script site names render with no bidi isolation and no language marking anywhere in the shell
    - **Severity**: **Low** — justified: the characters themselves survive intact (no mojibake, no truncation of the name — the heading uses `break-all` so long names wrap rather than overflow), so nothing is corrupted or hidden; the defect is presentation order for RTL runs inside LTR, neutral-aligned contexts, plus the a11y consequence of an unmarked language.
    - **Subsystem / file(s)**: `index.html:2` (`lang="en"`, no `dir` anywhere); `src/pages/site-detail.tsx:463-470` (the `<h1>` + URL line), `src/components/site-avatar.tsx:17` (`title={url}` on an `aria-hidden` span), `src/components/dom-diff-tree.tsx:169-171` (captured page text/attrs, `truncate`), `src/components/finding-card.tsx:68-74`/`UrlList` (captured URLs and matched page text), `src/components/bulk-import-dialog.tsx:243`. Grepped all of `src/`: zero `dir=`, zero `<bdi>`, zero `unicode-bidi`.
    - **Reproduction**: committed — `phase4f-capture-surface-repros.test.tsx::AUDIT-4F-7`: renders a site named `موقع الفجر — Журнал 東京` and asserts (a) `textContent` contains the exact string (code points intact) and (b) there is no `[dir]` attribute, no `bdi` element, and no `unicode-bidi` in the markup — i.e. the RTL run is subject to the bidi algorithm's neutral-alignment resolution with no isolation from its LTR neighbours.
    - **Root cause**: user-controlled strings are interpolated directly into LTR-only layout containers; no `dir="auto"` / `<bdi>` boundary exists for any of them.
    - **Proposed remedy category**: i18n/a11y polish — `dir="auto"` on the site name/URL/evidence-text elements (or a `<bdi>` wrapper), `lang` left as-is on the shell but the operator-supplied strings isolated so mixed-script evidence is rendered in the order it was captured.
    - **Source**: Gauntlet Step 4 — the phase's mandated "accessibility and mixed-script rendering" hunt.

    - **ID**: AUDIT-4F-7
    - **Title**: The risk gauge is an unnamed `role="application"` surface with no accessible name or value semantics
    - **Severity**: **Low** — justified: the numeric value and the words "Fused risk" are rendered as ordinary text directly beside the chart, so the number is *not* hidden from assistive tech; what is missing is a named, structured accessible representation and any statement of the threshold the value is measured against (a reader who cannot see the arc colour cannot tell a 42 % reading on a 30 %-threshold site from the same reading on a 60 %-threshold site).
    - **Subsystem / file(s)**: `src/components/risk-gauge.tsx:38-67` (recharts `RadialBarChart` inside a `Suspense` in `src/pages/scan-detail.tsx:270-274`); the tone comes from `riskTone`, i.e. colour-only.
    - **Reproduction**: committed — `phase4f-capture-surface-repros.test.tsx::AUDIT-4F-8`: renders `<RiskGauge risk={0.42} threshold={0.5} />` and pins the measured markup — the `svg` carries `role="application"` (recharts' accessibility layer) with `tabindex="0"` and **no** `aria-label`; no `role="img"` and no `[aria-label]` exists in the subtree; `textContent === "42%Fused risk"`; the word "threshold" never appears.
    - **Root cause**: the gauge was designed as a purely visual artefact; recharts' default `role="application"` plus an overlay `div` of text leaves no single element that conveys "value X vs threshold Y".
    - **Proposed remedy category**: a11y — give the wrapper an explicit accessible representation (`role="img"` + `aria-label="Fused risk 42 %, site threshold 50 %"`, or visible threshold text), and mark the recharts surface `aria-hidden` so the unnamed application role is not announced.
    - **Source**: Gauntlet Step 4 — the phase's mandated "screen-reader semantics for gauges/diffs" hunt.

    - **ID**: AUDIT-4F-8
    - **Title**: Alert- and remediation-queue risk chips are unconditional accent-red, including the `—` placeholder for an unmeasured risk
    - **Severity**: **Low** — justified: the mis-signal is in the *safe* direction (red = threat) and every chip sits beside its own text label and a status badge, so nothing reads as clean that is not; but a missing measurement is painted as maximally threatening, and these are the two surfaces an operator triages under time pressure.
    - **Subsystem / file(s)**: `src/pages/alerts.tsx:146` (`riskPct = alert.risk_score != null ? … : "—"`) and `:167` (chip className is a literal `text-accent-red`); `src/pages/remediation.tsx:125-126` and `:161` (identical shape).
    - **Reproduction**: committed — `phase4f-capture-surface-repros.test.tsx::AUDIT-4F-6`: asserts each file contains the `—` fallback and that the element rendering `{riskPct}` carries a literal `text-accent-red` with no conditional tone (no `?`, no `scoreTone`).
    - **Root cause**: the chip was styled once for the "this row is an alert" context, so the colour encodes *row class* rather than *value*; the null branch inherits it.
    - **Proposed remedy category**: same consolidation as AUDIT-4F-4 (route through the shared tone helper; neutral/mute tone for a null value).
    - **Source**: Gauntlet Step 3 — colour-clarity hunt, secondary surfaces.
- **ID**: AUDIT-4F-9
    - **Title**: One site-detail view fetches the same scan list twice on mount and then polls it on two independent timers
    - **Severity**: **Low** — justified: two requests return the same rows with different limits (`limit=20` for the table page, `limit=200` for the timeline), both are legitimately needed by different widgets, and no incorrect state was produced in any test or live view; the cost is a doubled per-view query load and a theoretical intra-view inconsistency (the table and the timeline can show the same scan at two different ages while a scan is in flight, because the timers are 2 s and 5 s and the caches are separate).
    - **Subsystem / file(s)**: `src/pages/site-detail.tsx:325-346` (`["sites", id, "scans", { page }]` @ `refetchInterval` 2000 while any row is `pending`/`running`; `["sites", id, "scans", "timeline"]` @ 5000 under the same condition), `:217` (`TIMELINE_WINDOW = 200`), `src/lib/api.ts::listScans`.
    - **Reproduction**: committed/measured — the AUDIT-4F-1 probe recorded the exact per-mount call set on 25 consecutive mounts, identical every time: `/api/sites/site-1`, `/api/sites/site-1/scans?offset=0&limit=20`, `/api/sites/site-1/scans?offset=0&limit=200`, `/api/sites/site-1/icon`, `/api/artifacts/baselines/baseline-1/screenshot` (the call-set log is preserved in `scratch/audit4f_flake_results.txt`).
    - **Root cause**: the timeline window was added as a second query rather than derived from the first; a superset fetch (`limit=200`) is already available to the table.
    - **Proposed remedy category**: query consolidation — one `listScans(0, TIMELINE_WINDOW)` query with a `select`/slice for the current table page (or a single shared `queryKey` with per-consumer `select`), one timer, one cache entry; keep the mutation invalidation as-is (prefix invalidation already covers both).
    - **Source**: Gauntlet Step 3/4 — the phase's mandated "queryKey scope / double-fetch storms" hunt.

- **Log-vs-reality discrepancies (Rule 12 — claims this phase could not reproduce as written)**:  
    1. **PROMPT-002's flake narrative vs measurement.** Its close-out log states the failure as `tests/capture-health.test.tsx "no hint when the baseline matches the current capture method" **hit its timeout at 11.8s** under full-suite load`, with the file "4/4 in isolation (**2.86s**)". Measured today: the *assertion* budget is **1016–1020 ms** (a `waitFor` timeout cannot produce an 11.8 s failure at any vitest config in this repo — `testTimeout` is unset, i.e. 5000 ms, and the failing assertion's own timeout fires first), while the *file's* wall time under full-suite load was 13.3–13.5 s and 4.0–4.8 s in isolation (cold start 13.3 s). The most likely reading is that "11.8s" was the file's wall time in that run, not the assertion timeout. Both numbers are recorded here rather than silently reconciling them: the *claim's* failure mode (a slow `waitFor`) is confirmed and root-caused; its stated magnitude is not reproducible as written.
    2. **PROMPT-002 Phase 7's "the degraded flag is what the site-detail and health aggregates key on"**: reproducible for `routers/health.py` (the fleet counts do read `degraded`), **not** for the site-detail page — no component reads it and the client type does not even declare it (AUDIT-4F-2). The log's claim is true of one surface and aspirational for the other.
    3. **PROMPT-003 Phase 1's re-execution claim** ("frontend `capture-health.test.tsx`: 4 tests passed") is confirmed — reproduced 45 times today, 0 failures.
    4. **AUDIT-4E-11 (carried, re-verified)**: the repo-wide format gate is still red at HEAD — `ruff format --check .` reports **24 files**; not re-run as a fix and deliberately untouched (Rule 1). The frontend gate (`pnpm lint` / `tsc -b` / `vitest run`) is green and was verified with this phase's new file included.
- **New hermetic tests added this phase** (`frontend/tests/phase4f-capture-surface-repros.test.tsx`, 11 tests, **committed-passing**: 3× `11 passed`, exit 0, file wall 6.3–6.4 s; full suite 22 files / 144 tests / 0 failed, exit 0, 3 passes):
    - `AUDIT-4F-1 …outlives the implicit 1000 ms waitFor budget` — deterministic repro of the flake mechanism (extant shape rejects on a *correct* payload at ≥900 ms; identical payload + explicit budget passes). *Diagnosis-of-defect style: a fix that adds the timeout makes this test fail, which is intended.*
    - `AUDIT-4F-2 renders Clean/0% with no degradation signal for a scan whose layers went dark` — pins the degraded-as-clean presentation using the authoritative `degraded_result` shape; also pins that `consecutive_degraded_scans` appears nowhere on the page.
    - `AUDIT-4F-3 omits a key the worker's layer summary emits, and never reads the streak` — cross-layer drift guard (parses `worker/scan_tasks.py::_summarize_layer_scores` and `src/lib/api.ts`, asserts the missing `degraded` key and the zero client references to `consecutive_degraded_scans`).
    - `AUDIT-4F-4 tones one layer reading two ways…` + `defines the tier functions without any threshold input` — the tier-consistency pair.
    - `AUDIT-4F-5 labels the gauge's 0.15 tier as the scheduler's material-change band (0.40)` + `hard-codes the beat tick the worker declares` — **AUDIT-2B-5 closed and O-8 implemented as an executable guard** (frontend source parsed against backend constants).
    - `AUDIT-4F-6 paints the unmeasured placeholder red on both queue surfaces`.
    - `AUDIT-4F-7 keeps the code points intact but adds neither dir nor bdi`.
    - `AUDIT-4F-8 exposes role=application with no accessible name and no role=img`.
    - `AUDIT-4F-9 tears the page down when the scans payload has no items array` — note: this test attaches `process` handlers for the duration of the assertion *deliberately*, because the defect escapes React entirely; without them vitest's own unhandled-error tracking would be the thing under test.
    - **Scratch (documented, not committed — deleted from `frontend/tests/` before the commit, Rule 5/10)**: four instrumentation files (`_scratch-4f-flake-probe`, `-probe2`, `-probe3`, `-probe4`) used to measure the assertion budget, the call set, the 25-mount latency series, the risk-gauge markup and the shape-skew crash. Their findings are folded into the entries above; the durable evidence is the preserved probe scripts + result logs under `Prompts/Pending/Finders/PROMPT-003/scratch/` (`audit4f_vitest_flake_probe.ps1`, `audit4f_flake_results.txt` (45-pass matrix), `audit4f_flake_load_probe.ps1`, `audit4f_flake_load_results.txt` (20/20), `audit4f_final_batch.ps1` + `_results.txt`, `audit4f_definitive_batch.ps1` + `_results.txt`; the bulky per-run JSON dumps were deleted for size). One honesty note: leaving those scratch files in place made `vitest run` exit **1** while all tests passed (a leaked uncaught error from a probe's own fixture) — which is why the suite's exit code was re-verified after their removal; the committed file alone exits 0 (3×).
- **Opportunities / Innovation ideas observed** (Rule 17 — not severity-scored, not gap-driven):
    - **Idea**: put the *latest verdict and capture-degradation state on the Overview tab* (the view an operator lands on shows no verdict at all — badge/dot/risk live behind the "Scans" tab).
    - **Why it would help**: the first screen after opening a site answers "is it okay right now, and did we actually measure it?" without a tab switch, and makes AUDIT-4F-2's remedy visible where it matters.
    - **Where it touches**: `frontend/src/pages/site-detail.tsx` (Overview tabpanel), reusing `verdictBadge`/`riskCell`/`StatusDot`.
    - **Rough shape of the change**: a small summary card fed by `scans.data.items[0]` + `s.consecutive_degraded_scans`; no new endpoint.
    - **Idea**: one `riskTone(value, threshold)` module + one tier-constant export adopted everywhere (closes AUDIT-4F-4/4F-8 by construction and deletes the literal the AUDIT-4F-5 comment lies about).
    - **Why it would help**: a single source of truth for severity colour makes green/orange/red mean one thing across capture, detection, alert and remediation surfaces; today one value reads two ways.
    - **Where it touches**: `src/lib/` (new module), `finding-card.tsx`, `scan-detail.tsx`, `risk-gauge.tsx`, `site-detail.tsx`, `alerts.tsx`, `remediation.tsx`, `incident-timeline.tsx`.
    - **Rough shape of the change**: export `riskTone(value, threshold)` returning a token name; replace the seven inline tier expressions; design tokens unchanged.
    - **Idea**: a shared authenticated-blob cache for artefacts and icons.
    - **Why it would help**: `useSiteIcon`/`useArtifact` bypass React Query entirely — one HTTP request *per component mount* with no dedupe, cache or TTL (an N-row sites list issues N icon requests on every visit and again after navigation), and blob URLs are revoked per unmount so nothing is reused.
    - **Where it touches**: `src/lib/use-site-icon.ts`, `src/lib/use-artifact.ts`, `src/components/{site-favicon,site-avatar,visual-diff-slider,dom-diff-tree,suppression-panel}.tsx`.
    - **Rough shape of the change**: wrap both hooks in `useQuery(["icon", id] / ["artifact", path], …, { staleTime })` with a process-wide blob registry keyed by path and refcounted revocation.
    - **Idea**: response-shape validation at the `api()` boundary + a root error boundary (turns AUDIT-4F-3 from a blank page into an explicit "data contract mismatch — reload" state).
    - **Why it would help**: every contract drift in the frontend currently becomes either a silent `undefined` render or a teardown; central validation converts the class into one visible, recoverable state.
    - **Where it touches**: `src/lib/api.ts` (a `paged()` guard validating `items`/`total`), `src/App.tsx`/`main.tsx` (boundary).
    - **Rough shape of the change**: a small guard per payload family throwing `ApiError(200, "unexpected response shape")`; one class-component boundary around the routed tree.
    - **Idea**: surface the superseded-scan taxonomy in the UI (carried from AUDIT-4B).
    - **Why it would help**: `"Scan never completed — superseded by a scheduled scan"` renders as a plain truncated error string in the scans table, so bookkeeping and a genuine detection failure look identical in history.
    - **Where it touches**: `src/pages/site-detail.tsx` (error cell), optionally `ScanDetailOut`.
    - **Rough shape of the change**: match the supersede marker (or persist a `superseded` reason) and render a distinct neutral badge.
    - **Idea**: generalise the O-8 "comment-asserts-constant" check into a repo-wide script/CI step.
    - **Why it would help**: this phase's guards are two hand-built instances and the class is proven repo-wide (`fusion.py`'s own 0.35-vs-0.40); a generic reader (comment → literal → named constant → current value) makes drift a standing report instead of per-audit luck.
    - **Where it touches**: `backend/tools/` (e.g. `tools/check_constant_drift.py`), CI.
    - **Rough shape of the change**: parse comments for `constant (value)` patterns plus file-local literals compared against same-named constants elsewhere; report mismatches only, never auto-fix.
    - **Idea**: delivery-health rollup on the health page (re-confirms AUDIT-4D's O-4D-1 from the UI side: Alerts has per-delivery rows, Health has no delivery aggregate).
    - **Where it touches**: `src/pages/health.tsx` + `routers/health.py` (mirroring the capture-quality rollup).
    - **Rough shape of the change**: `alerts_24h` / `deliveries_failed_24h` beside the capture-quality tile.
- **Full regression results** (Rule 13 — every count from an actual run this session; Windows host, Docker stack up and used read-only; vitest 4.1.10 / jsdom 29 / React 19):
    - New repro file: `cd frontend && pnpm exec vitest run tests/phase4f-capture-surface-repros.test.tsx` → **11 passed, exit 0**, walls **6.4 / 6.4 / 6.3 s** (three consecutive passes; per-test durations stable to ±10 ms, the flake test ≈2.51 s by construction).
    - Full suite: `pnpm exec vitest run` → **22 files / 144 tests / 0 failed, exit 0**, walls **12.8 / 13.1 / 12.4 s** (three consecutive passes; 144 = the pre-existing 133 + this phase's 11).
    - Flake characterization (Rule 18): `capture-health.test.tsx` → **15/15 isolated green** (walls 4.0–4.8 s, cold first run 13.3 s), **3/3 full-suite green** (file wall 13.3–13.5 s), **20/20 green at K=5 concurrent load** — **45 passes, 0 failures**; the duration series and the load matrix are in `scratch/audit4f_flake_results.txt` and `scratch/audit4f_flake_load_results.txt`.
    - Gates: `pnpm lint` → **exit 0** (0 errors / 13 warnings — unchanged from AUDIT-4E's baseline; no new warning introduced by the new file); `pnpm exec tsc -b` → **exit 0**, no output. AUDIT-4E-11's `ruff format --check .` 24-file backend failure was **not** re-run as a fix and is untouched (Rule 1).
    - AUDIT-4E-10 carried: `vitest@4.1.10` / `@vitest/mocker` moderate dev-only advisories remain below the `pnpm audit --audit-level high` gate (exit 0). Noted, not chased.
    - Live stack: re-attested after the user's rebuild (6 containers up, `wardress-app-1` healthy on :8321, post-HEAD `/app/static` bundle verified). No write actions were issued against the live system this phase (read-only inspection only; no sites/users created, none removed).
    - No production file was modified (Rule 1) — this phase's diff is one new test file, one log entry, the Phase Map status line, and the preserved scratch probes.

- **Findings out of phase scope** (logged for the correct future phase, not investigated here):
    - `worker/detection/fusion.py:40` and `:192` asserting 0.35 against the current 0.40 bar — same defect shape as AUDIT-4F-5 but on the *detection* side; evidence recorded above, remedy belongs to the detection remediation scope (AUDIT-4-*/AUDIT-3-*), cross-referenced rather than re-derived.
    - `src/components/dom-diff-tree.tsx`'s green-means-added / red-means-removed legend collides with the app-wide green-means-clean vocabulary — recorded under AUDIT-4F-4's remedy list rather than as a standalone finding, since its fix is the shared tone module.
    - The engine-side counterpart of AUDIT-4F-2 (findings rows carrying no `degraded` column) remains AUDIT-4's Lead 1 — the frontend-side fix proposed here does not require a schema change, but the backend change is where the *evidence* (per-layer reason text) becomes first-class.
    - Backend `ruff format --check .` (24 files) is AUDIT-4E-11's item; the remediation prompt owns it.
    - `frontend/tests/*`'s remaining 20 files were cold-read for coverage inventory and convention (no setup file, no `globals: true`, so every file must clean up itself — `capture-health.test.tsx` and `health-honesty.test.tsx` do; `no-third-party-image-hosts`/`svg-path-integrity` are source-scanning tripwires). A deeper test-suite *coverage* audit was not in this phase's scope and is offered to Phase 9/10 as an optional sweep.
- **Commit**: `95bd60e` — test(audit-4f): frontend capture/detection surface repro tests + flake characterization probes (diagnosis only); this log entry is committed immediately after, referencing that hash (not pushed).
- **Next phase kickoff prompt**: delivered in chat only — never written to this log.

---

### [DONE] PROMPT-003 Session A — Deep Verification of Completed Phases (1–4F)

- **Prompt**: SESSION-A-KICKOFF.md (coordinator model; §0/§1/§2/§6.4 of the main spec govern every subagent)
- **Session date**: 2026-09-30
- **Scope**: Independent deep verification of all ten completed audit phases (1, 2, 2B, 3, 4, 4B, 4C, 4D, 4E, 4F) by **five parallel subagents**, each operating with full investigative liberty (Rule 17), diagnosis-only (Rule 1), and every finding reproduced (Rule 4) or measured over ≥3 passes (Rule 18).
- **Subagent reports** (Rule 10 — preserved in-repo as this effort's evidence; all raw probe scripts live outside the repo under `%TEMP%\opencode\wardress-session-a\`):
  - `scratch/session-a-capture.md` — Audit Phases 1 + 3 (capture) — 467 lines
  - `scratch/session-a-detection.md` — Audit Phases 2 + 4 (detection) — 583 lines
  - `scratch/session-a-orchestration.md` — Audit Phases 2B + 4B (orchestration) — 680 lines
  - `scratch/session-a-api-frontend.md` — Audit Phases 4C + 4F (API/auth/frontend) — 968 lines
  - `scratch/session-a-ai-infra.md` — Audit Phases 4E + 4D (AI/supply-chain/delivery) — 823 lines
- **Environment attestation (Rule 13)**: Docker stack up and healthy (`wardress-app-1` on :8321, worker/beat/db/redis). The disposable test database `wardress-test-pg` **had been deleted**; it was recreated this session with the command documented in `backend/tests/db_harness.py:98` / `README.md` ("Backend Development") and pinned to `127.0.0.1:5433`, user/pass `wardress`/`wardress`. Each subagent ran against **its own dedicated database** (`wardress_sa_capture_test`, `wardress_sa_detect_test`, `wardress_sa_orch_test`, `wardress_sa_api_test`, `wardress_sa_ai_test`) so no two ever shared the single-contract harness. No install/uninstall/update script was run. The live stack was used **read-only** by all five subagents (no container stopped/restarted/rebuilt/pulled; no throwaway live users or sites left behind).
- **Rule 1 compliance**: `git diff --stat HEAD` is **empty**. Zero production files modified across the whole session. No subagent ran a git state-changing command and none committed.

#### Summary

| Metric | Count |
|---|---|
| Finding blocks logged by the five subagents | **106** |
| **New findings** | **45** |
| **Findings deepened** (new edge cases, wider blast radius, corrected numbers, or severity change) | **37** |
| **Findings confirmed** unchanged | **23** |
| **Findings invalidated** | **1** + 4 invalidated/partial hypotheses |
| Cross-subsystem interactions identified | **10** |
| Dead-code / orphan items proven | **~55** across 5 subsystems |
| New hermetic test files | **3** (138 tests, all passing) |

**Severity distribution across all 106 blocks** (one honest severity each, per §6.4; 4F's own "conservative" split is preserved):

| Severity | Count | Notable |
|---|---|---|
| **Critical** | **7** | AUDIT-SA1-1, AUDIT-SA2-2, AUDIT-SA2-3, AUDIT-4-1, AUDIT-4E-1, AUDIT-4E-2, AUDIT-4E-4 |
| **High** | **17** | AUDIT-SA1-2, AUDIT-3-1 (escalated), AUDIT-3-4 (escalated, partial), AUDIT-2-4, AUDIT-SA2-1, AUDIT-4-2, AUDIT-4-4 (new half), AUDIT-4-5 (escalated), AUDIT-4B-1, AUDIT-SA3-1…4, AUDIT-4D-1, AUDIT-SA5-1, AUDIT-4E-8 (escalated), AUDIT-4E-10 (escalated) |
| **Medium** | **~40** | incl. AUDIT-1-1 (downgraded with justification), AUDIT-4B-5/-4B-6 (escalated), AUDIT-4C-1/-4C-2, AUDIT-4F-2/-4F-3, AUDIT-SA4-1/-2/-3/-5/-8/-9, AUDIT-4E-3/-5/-11, AUDIT-4D-2/-3/-4, AUDIT-SA5-3/-4 |
| **Low** | **~42** | remainder |

**Headline of Session A:** the ten completed phases were **honest and technically strong** — nothing was fabricated, several prior findings were *strengthened* rather than merely re-asserted, and one prior finding was fully invalidated. But independent verification found **three Critical SSRF-class holes and two Critical false-"clean" attack paths that no prior phase detected**, plus a **measured** false-positive rate on the model's own training data (34 of 323 benign rows exceed the default flag threshold) that turns AUDIT-2-4's "unproven overfitting risk" into a demonstrated alert rate.

---

#### Confirmed Findings (verified still present, with the deepening Session A added)

| ID | Title | Prior severity | Session A severity | What Session A added |
|---|---|---|---|---|
| AUDIT-3-1 | Banner click can store the WRONG page | Medium | **High** | Root cause reproduced 3/3 through production `fetch_page` with a server-side request log. **The challenge gate is defeatable through the banner click**: a control whose `aria-label` matches the generic fallback and which navigates into a Cloudflare interstitial is captured as **challenge HTML with `cloudflare_challenge_detected: False` and `capture_quality: "full"`** — a direct violation of Phase 2's headline contract. `FetchResult` is internally self-contradictory (`final_url` pre-click, `http_status`/`headers` post-click). The stale `final_url` reaches `baseline.capture_meta`, `ScanPageData.final_url`, and therefore `detection/dom.py:651` (relative-URL base) and `:699` (same-host allowance) — a presentation-layer bug becomes a detection-accuracy bug. |
| AUDIT-3-2 | Late-attaching consent iframes never dismissed | Medium | Medium | Prior root cause was **incomplete**: iframe nesting is a red herring (`page.frames` is flat and already includes grandchildren — 4 frames found at 3 levels). The two real causes are (a) the single `_frames(page)` snapshot, reproduced exactly (`attempts=30` = 1 frame while `len(page.frames)==2`, the iframe *was* fetched per the server log), and (b) **NEW**: `_clickable_in_viewport` compares a **page-coordinate** bounding box against `page.viewport_size` and never scrolls the element into view, so a `position:fixed` consent control inside an iframe appended at the end of `<body>` is rejected (measured: `y=78.4` → dismissed; `y=2578.4` → not dismissed, 60 attempts, 3.14 s). |
| AUDIT-3-3 | SSRF rebinding window on the Playwright path | Medium | Medium | Cache widening confirmed (10 URLs → 3 `assert_url_allowed` calls). **New defect**: the cache key `f"{scheme}://{host}"` **omits the port**, so `https://cdn.example.com:8443/x` inherits the verdict for `:443`. **Honest counter-argument the prior log did not make**: Chromium maintains its own per-profile host resolver cache honouring the record TTL, so same-host rebinding inside one page load is unlikely to be re-resolved at all — the real risk is staleness against policy change, not rebinding. The finding is **largely subsumed** by AUDIT-SA1-1, which needs no timing at all. |
| AUDIT-3-4 | Artifact janitor gaps / non-atomic writes | Low | **High** (write path) + **Medium** (retention path) | Split, because the two halves meet different §6.4 bands. **(a) Data corruption**: non-atomic `write_text`/`write_bytes` + `store_artifacts` running *before* the DB commit means a kill mid-write leaves a **truncated `page.html` behind a row that still reads `status='completed'` with a valid `content_hash`** — all nine layers then diff the truncation → maximal bogus diff → `flagged` → alert. The janitor cannot help because the row exists. **(b) Retention**: an exhaustive grep proves **nothing in the repo ever deletes a `Scan` or `Baseline` row** — the janitor's only criterion is row *absence*, so every artifact directory whose row survives lives forever regardless of age or terminal state, and the 500-removals-per-run cap means a backlog never fully drains at scale. |
| AUDIT-3-5 | Capture-completeness facts never reach detection | Medium | Medium | The loss point is **one constructor call**: `ScanPageData(...)` at `scan_tasks.py:280-292` takes 9 scalar fields, none of them a completeness flag. Full write-only-evidence inventory produced: **17 of the 19 `capture_evidence` keys have zero production readers**, including `retry_count` (added by Phase 6) and `capture_wall_clock_ms` (added by Phase 7 specifically for triage). |
| AUDIT-3-6 | Per-scan request multiplication x adaptive cadence = WAF escalation loop | Low | Low | Confirmed by measurement: `probe_site` makes 4 sequential requests (robots + 3 UA fetches), measured 1.766 / 1.609 / 1.625 s under 400 ms injected latency; the loop holds `max_connections=4` idle for 3 of 4 slots, so the parallelism headroom is already provisioned and unused. The `googlebot` UA ships on every scan from Wardress's IP. |
| AUDIT-3-7 | `hashing.py` latent `content_sha256(None)` crash | Low | Low | Re-confirmed (`AttributeError` on `None`, `TypeError` on `bytes`). **New in the same layer family**: `probe.py:128-131` is a provably dead branch — `getpeercert()` returns `{}` under `verify_mode=CERT_NONE`, so `if peer:` is always falsy and `_name_attrs` can never run; the consequence is that `subject`/`issuer` are **silently absent from every TLS record** whenever the `cryptography` parse fails (a silent evidence gap in layer 6, not a cosmetic dead branch). |
| AUDIT-3-8 | `auto_scroll_page` counts a shrinking height as stable | Low | Low | Present. Deepened: the related `stalled` condition *also* requires `height <= last_height`, so a collapsing page (virtualised list unmounting on scroll-up, ad slot collapsing after lazy-load) ends the walk early; the `finally` `scrollTo(0,0)` then fires and the screenshot is taken at the top of a page whose below-break lazy content never loaded — with `capped=False` and `stable` possibly `True`. |
| AUDIT-1-1 | "changed, not clean" on benign dynamic content | High | **Medium** (downgraded, with justification) | **The logged cause is the minor part.** Eleven out-of-family benign churn shapes measured over 3 passes each fuse to **0.1907–0.2213** (pstdev 0.00000) and read `changed`; but `layer1_hash` alone is only `sigmoid(4.408 − 6.247) = 0.1372` of that, and the residual 0.06–0.08 is layer 2's content-churn term and layer 3's `min(0.4, 0.02 × total_new_refs)` — both *designed* to read non-zero on real churn. **Consequence: Phase 1's own proposed remedy (exclude the byte-hash when all content layers are sub-noise) would NOT deliver `clean`** — measured, an 8-article lazy append keeps `layer2 = 0.1231 > NOISE_FLOOR`. Only a byte-identical pair reads `clean`. Remedy design must change: a third verdict state, or gate `changed` on the *content* peak excluding l1 **and** the generic churn term. |
| AUDIT-2-4 | NOISE_FLOOR / MATERIAL_CHANGE_RISK overfitting | High | High | **Converted from an unproven risk into a measured alert rate.** Re-fusing every row of the committed 646-row `fusion_dataset.json` through the deployed `layer9_fusion`: **36 of 323 benign rows reach 0.40; 34 exceed the default 0.50 flag threshold.** `vendor_script_added` (a benign axis) averages **0.7538** with max 0.8269 — 100% of that axis flags. `sanity_benign_quiet`, a row whose entire purpose is to prove the harness is calibrated, scores **0.6583**. The 152-row corpus guard is *circular*: its benign axes are 7 of the 14 benign axes, and the 7 it omits are exactly the ones that cross the bar (0 corpus benign rows cross 0.40). Phase 12's "strict subset" decision removed precisely the axes that would have exposed this. |
| AUDIT-4-1 | `_new_text` granularity collapse on unpunctuated pages | Critical | **Critical** | The logged numbers were the **weakest** fixtures. The collapse is total: `_new_text == extract_visible_text(current)` verbatim (100.0% of the page) in **7 of 9** adversarial shapes (unpunctuated, emoji-only, numbers-only, mixed script without Latin punctuation, CJK without sentence markers, 51 KB single-line minified text, single-line DOM text). End-to-end over `run_detection`, a **one-word edit** reaches **risk 1.0 / `flagged`** in 6 realistic baseline fixtures (security write-up with `hacked by`; 3 profanity terms; aggression lexicon with `regime`/`traitors`; Chinese `被黑`; security-blog topic words; `telegram` contact). The rule floor `conclusive_signature_text` fires at 0.90. Both preconditions are *routine* on the live web (a) and (b). Deepened cause: `aggression_score = 1 − exp(−1.2·Σw)` has **no cap** on `Σw` while `topic_score` is capped at 0.7 — an asymmetry that is why the aggression channel reaches maximal severity. |
| AUDIT-4-2 | Probe transients read as measured evidence (layer 6) | High | High | **The logged fused risk is understated.** With the `layer1_hash = 1.0` any real byte-changing scan carries, a current-side TLS probe failure fuses to **0.5502 — above the default 0.50 flag threshold**, i.e. one failed handshake on an otherwise-unchanged site produces an `Alert` + `RemediationExecution`. The log's 0.429 must have had a different layer-1 profile. `robots.txt` transients confirmed in both directions (0.15 each, neither degrades). |
| AUDIT-4-3 | Statically expired cert scores 0.5 forever | Medium | Medium | **The logged "risk stays ~0.01" is understated by ~50x.** Measured with `expired=True` on both sides: `l6 = 0.5`, **fused risk 0.4857**, verdict `changed` forever — and because `0.40 <= 0.4857 < 0.75`, **every scan of a statically-expired site burns an LLM escalation call and permanently pins cadence to `base/4`**. The static-expiry case is *indistinguishable in the score* from a genuine expiry transition. |
| AUDIT-4-4 | Suppression timeout asymmetry | Medium | Medium + **new High half** | Asymmetry half confirmed. **Two corrections to the prior log**: (a) only *alternation*-based bombs like `(a|aa)+b` actually time out — `regex`'s optimizer defeats `^(\w+\s?)+$`, `([a-zA-Z]+)*!`, `(.*,)*[0-9]+`, `(\d+)+#`, all ≤1.5 ms, so the "ReDoS immunity" claim is true for `normalize.py` (18 adversarial docs, max 99.9 ms on a 2 MB document, zero raises) and true for *common* user patterns but not absolute; (b) **the logged cost claim is unreachable** — 60 pathological nodes under one timing-out rule cost **2.00 s total**, not nodes x 2 s, because the `TimeoutError` aborts the whole element loop at the first node. **NEW, and the more serious half: an over-broad suppression rule permanently blinds layers 5 and 8 with no coverage signal.** A conclusive defacement scores `flagged` at 1.0 unsuppressed; with one rule of `css_selector *`, `body`, `main`, `regex .*` or `[\s\S]+` it drops to `changed` at 0.195. `build_suppression` accepts these with no warning and no size check, and `suppression_applied` evidence records only *which* rules ran — not how much content they removed. Since suppression runs **before every content layer and replaces the content on both sides**, a suppressed span is invisible to layers 2/3/5/8 entirely, which is also the primitive an adversary who can guess a common selector (`#banner`, `[role=alert]`, `.cookie-consent`) would use. |
| AUDIT-4-5 | Empty/unparseable capture is a measured 1.0 | Medium | **High** | Escalated: the logged case reads `changed` at 0.4837, but the **mirror case is a false `clean`**. Two new sub-cases: **(a) a binary/undeclared-content capture FLAGS** — raw binary junk gives `layer2 = 1.0` (total structural annihilation) and `layer8 = 0.9738` (MiniLM cosine on binary noise) → **risk 0.9833, `flagged`**, creating alert + remediation rows from a capture bug; `drift_from_similarity` has no content-type guard. **(b) BOTH sides empty reads `clean`** — identical `content_sha256("")` makes `identical = True`, so layers 2/3/5/8 get `skip_result` (a *proof of zero* per the module docstring) and `layer4` degrades; the system's own designed distinction between "provably zero" and "unmeasured" is **inverted** by an empty page pair. |
| AUDIT-4-6 | Layer 3 is removal-blind | Medium | Medium | Confirmed and **generalised**: all five reference kinds score exactly 0.0 on removal (script, iframe, form, link included, not just scripts/iframes). **New layer-2 sub-case**: hidden-element *additions* are the sensitive channel (`max(0, current − baseline)`), so **un-hiding** a hidden SEO farm by dropping `style="opacity:0"` produces `layer2 = 0.0` with `structural_churn = 0` — a completely silent transition from invisible spam to visible spam. Positive control: a legitimate security hardening (removing a Turnstile widget) is equally invisible, so the system is at least internally consistent. |
| AUDIT-4-7 / AUDIT-4-8 | The two Phase-3 handoff specifications | Medium | Medium | Both specifications still match the code. **Three corrections to the specs themselves** (which the kickoff asked for): (1) AUDIT-4-7's "crop both to the capped extent" for layer 4 is **already partly done** — `_common_size` already takes the min scaled height; the uncropped part is only the pHash/dHash pair, so the remedy is a narrowing not a new mechanism; (2) AUDIT-4-8's "run hidden-state resolution symmetrically" is **already symmetric** — `_tree_stats` builds its own `_HiddenContext` per side; the real exposure is the absolute count dropping when rules move to a sheet the capture never fetched; (3) AUDIT-4-7's "partial-confidence scalar into fusion" needs a numerical guard the spec does not give — measured, `layer3 = 0.9` with one degraded channel lands at **exactly 0.4000** and is *not* bounded by `_UNMEASURED_RISK_CEIL` (which only bounds the uplift). |
| AUDIT-2-1 / -2-2 / -2-3 | Taxonomy gaps; 3 genuinely-absent attack families | Med / High / Med | unchanged | Re-verified and **evasion scenarios now measured end-to-end**: subtle single-word tampering `two weeks` -> `two days` = 0.1942; `<meta http-equiv=refresh>` = 0.1987; client-side `location.replace` cloak = 0.3153; same-origin phishing overlay = 0.2242 (only a *new-domain* overlay is caught, at 0.5450 — the less likely case). **Two refinements to the prior log**: (a) the time-delayed family is **not** genuinely absent when the payload is DOM text (risk **1.0**, `flagged`) — only the timed-`<script>`-string form evades (0.3153); (b) **attack withdrawal IS caught, by layer 4** (banner removed = a 0.296 visual delta -> 0.9976 `flagged`), a genuine positive no prior phase tested, though asymmetric (a phishing overlay's withdrawal only reaches 0.2249). `nonnative_full_rewrite` / `nonnative_partial_inject` confirmed still absent from the 19-axis corpus. |
| AUDIT-2-5 | `ScanFinding` has no `degraded` column | Medium | Medium | Re-read: the columns are exactly `id, scan_id, layer, layer_key, score, skipped, evidence, created_at`. Concrete consequence now measurable: a scan where *nothing was measured* has `layer2/3/5/8` rows byte-identical in shape to a layer-4 screenshot loss. |
| AUDIT-2-6 | `capture_meta["headers"]` unused | Low | Low | Repo-wide grep over all 100 `backend/**/*.py`: one write, one *unrelated* reader (`app/explain.py:98` reads layer-6 **evidence**, not `capture_meta`). Unchanged. |
| AUDIT-4B-1 | Lost alerts on worker death | High | High | **The window is 10.1 ms median / 26.8 ms max** (5-pass measurement), not "sub-second" — which makes it *rarer* but also means it is essentially an atomicity problem, not a race. The materially larger variant is the DB-hiccup one, which is **unbounded**: an `OperationalError` inside `_create_alert`'s commit propagates, the wrapper's `_mark_scan_failed` no-ops on the completed row, the task returns "error" and is **ACKed** — no redelivery, no recovery sweep. |
| AUDIT-4B-2 | Overload amplification | Medium | Medium | **Entry threshold quantified**: amplification begins at a backlog of ~15–60 pending rows — *one over-capacity tick*. Saturation at ~2,160 sites at base cadence, ~500 at `base/4`, or **7–8 sites at the 5-minute floor**. Overload soak deliberately not run live (would saturate the shared stack); the supersede path itself was verified hermetically. |
| AUDIT-4B-3 | Cadence pinning from transients | Medium | Medium | Simulated: **4 consecutive clean scans are needed to return to base (24 h at `base/4`)**. A site with a *daily* transient therefore **never returns to base — 0 of 500 simulated sites do, in 30 days**. Measured live tick drift is 64.18 s mean. |
| AUDIT-4B-4 | Re-baseline does not arbitrate in-flight scans | Low | Low (**CONFIRMED, accepted-risk is correct**) | Independent re-assessment: a scan-side 409 would block the operator for up to 8 minutes and kill useful concurrent work; `scans.baseline_id` already makes the anchor fully traceable. "Accepted-risk" is the right call — recorded so it is not re-litigated. |
| AUDIT-4B-5 | Stale-row recovery latency bounded by `next_scan_at` | Low | **Medium** (baseline half) | Worst case for a 24 h site measured as **interval + 2 x STALE_INFLIGHT = 24 h 20 min**. **Escalated on a new half**: stuck `pending`/`capturing` **baselines have no beat-side stale sweep at all** — verified, a 30-minute-stuck baseline survives all four periodic tasks untouched, the tick reports it as a benign `skipped_no_baseline` forever, and the site is **permanently unmonitored** with no operator signal. Only an operator action recovers it. |
| AUDIT-4B-6 | Heartbeat measures tick execution, not beat liveness | Low | **Medium** | Escalated: the heartbeat is written **on the success path only**, so it is skipped on *any* dispatcher failure — a plain database outage makes the operator's only scheduling signal go red while the stack is otherwise healthy. **New**: 4 of the 5 periodic tasks have `expires == interval` exactly, pinned against Celery's own silent drop site (`worker/strategy.py:162`), and `REDELIVERY_GRACE == REDELIVERY_SWEEP_SECONDS == 300 s` with no margin. |
| AUDIT-4B-7 | Worker memory ceiling, no child recycling | Low | Low | Re-measured: **624.5 MB warm child, and GC returns only 0.2 MB** — the footprint is non-reclaimable. 12 warm children extrapolate to **5.90 GiB of a 7.429 GiB host ceiling = 79 %**. **`--max-tasks-per-child` provably does *not* help** (the model memory is never released), which narrows the prior log's remedy list. |
| AUDIT-4B-8 | Deployment drift | Low | **Low, residual only** | See *Invalidated* below. |
| AUDIT-4C-1 | 503 partial-success on dead broker | Medium | Medium | Reproduced end-to-end at the HTTP layer. Bulk-import contrast quantified: the bulk path already has the right shape ("created — baseline capture could not be enqueued … use Rebaseline once it is back") and single-create never got the parity pass. |
| AUDIT-4C-2 | `/docs`, `/redoc`, `/openapi.json` public and unmetered | Medium | Medium | **Fourth public route found**: `/docs/oauth2-redirect` (3012 B live). Live schema 92,500 B. **The schema narrates the SSRF gate and names the endpoints that probe internal networks** — the `allow_private_networks` field, the `sitemap` fetch, and the SSRF-related description text. **One sub-claim invalidated** (the `wk_` key prefix: 0 hits over the 99,585-byte schema — it lives in `app/apikeys.py`, not the published schema); the finding stands on 8 stronger items. |
| AUDIT-4C-3 | Two mute implementations, divergent audit snapshots | Low | Low | Confirmed. |
| AUDIT-4C-4 | `DELETE /api/sites/{id}` has no in-flight guard or cascade disclosure | Low | Low | Footprint measured: the cascade destroys baselines, scans, suppression rules, alerts + deliveries, per-site channels, and remediation hooks + executions — irreversible, with a 204 and an empty body. **New**: the endpoint has no UI caller at all, so the only way to delete a site is the API. |
| AUDIT-4C-5 | health.py readiness docstring cites a dead healthcheck | Low | Low | Confirmed, and the drift is now **public**: the readiness route's own docstring advertises a compose healthcheck that no longer exists. The residual note is now measured — `GET /api/health` returns **200 in both the healthy and the database-down branch** (see AUDIT-SA4-9) and discloses "database unreachable" detail to an unauthenticated caller. |
| AUDIT-4C-6 | Three routes double-charge the per-user rate limit | Low | Low | Confirmed; **effective budget measured at 10 instead of 20** on a 20/min configuration. |
| AUDIT-4C-7 | `DELETE /api/users/{id}` hard-deletes regardless of usage | Low | Low | Confirmed, plus **new**: the endpoint has no UI caller, so the "never-used account cleanup" precondition the docstring promises is not just unenforced — it is unreachable in practice. |
| AUDIT-4F-1 | `capture-health.test.tsx` flake | Low | Low | **Minimum triggering delay measured at exactly 1000 ms and it is load-independent** — the implicit `waitFor` budget, not a race and not test-state leakage. Both Phase-4F committed guards (`phase4f-capture-surface-repros.test.tsx`, `capture-health.test.tsx`) still pass at HEAD. |
| AUDIT-4F-2 | Degraded renders as Clean / 0% | Medium | Medium | Confirmed. `consecutive_degraded_scans` is still referenced by **zero** files under `src/`. |
| AUDIT-4F-3 | Blank dashboard on shape mismatch | Medium | Medium | **6 of 19** malformed payload shapes blank the whole dashboard, at **3 distinct unguarded expressions**, affecting **4 of the 10 routes**. Reproduced through React's own teardown path. |
| AUDIT-4F-4 | Severity colour defined eight ways | Low | Low | Deepened from 4F's five: three more found, and the vocabulary collides *inside a single card*. |
| AUDIT-2B-5 / AUDIT-4F-5 | `risk-gauge.tsx` comment asserts a moved constant | Low | Low | Confirmed, and **AUDIT-2B-5 is now closed into an executable guard** that still passes at HEAD. |
| AUDIT-4F-6 / -4F-7 / -4F-8 / -4F-9 | bidi isolation; unnamed `role=application` gauge; unconditional-red unmeasured chip; duplicate scan-list fetch | Low | Low | All four confirmed unchanged. |
| AUDIT-4D-1 | Mid-delivery crash orphans remaining channels forever | High | High | **Now deterministically reachable from user-controlled data**: a **CR/LF in a site name** raises `ValueError` out of `deliver_to_channel`, permanently orphaning every channel after that point with **no delivery row at all**. Real window measured as `40 s x (channels − 1)`. **Positive result recorded too**: the email HTML body is verified **safe** — Jinja autoescape is on, there is no `|safe`, and a hostile site name survives premailer intact. |
| AUDIT-4D-2 | Check-then-act idempotence guard double-sends | Medium | Medium | Confirmed, with reachability analysis added (resweep re-enqueue during an in-flight delivery past the 5-minute grace). |
| AUDIT-4D-3 | Favicon resolver on an unpinned httpx client | Medium | Medium | Confirmed; hop-by-hop redirect matrix re-verified (redirect-to-internal remains closed). |
| AUDIT-4D-4 | Favicon "size-capped" claim not delivered | Medium | Medium | **Quantified with `tracemalloc`: a 32 MiB body produces a 64.2 MiB Python heap peak on the API event loop** before truncation returns 65,537 bytes. |
| AUDIT-4D-5 / -4D-6 / -4D-7 / -4D-8 | Cooldown anchor; channel-less resweep; non-retroactive manual-confirm; concurrent explain | Low | Low | All four confirmed unchanged. |
| AUDIT-4E-1 | SSRF policy skipped by one AI provider writer, never re-checked on execution | **Critical** | **Critical** | **A third, previously-unnamed reader path exists**: `resolve_tool_capability -> Ollama /api/show` POSTs to the stored `base_url` on a raw httpx client with **zero** SSRF checks and no rate limit. **The private-network allowance is keyed on provider *type***, which permits `169.254.169.254` / `100.100.100.200` / `fd00:ec2::254` (measured) while the default policy refuses them; and `normalize_base` performs no scheme/credential sanitisation (5 hostile shapes pass through). |
| AUDIT-4E-2 | models.dev catalog fetch outside the SSRF policy, unpinned client | **Critical** | **Critical** | **And the fetched data is trusted past its schema**: a list-shaped `providers` key makes `AttributeError` escape `fetch_live_catalog`, falsifying the module's documented "never raises" contract (this one *can* break startup). `upsert_catalog` refuses an empty model set but not a structurally wrong one. |
| AUDIT-4E-3 | Hung provider stalls one 30 s timeout per key/deployment | Medium | Medium | Re-measured over **6 passes**: 31.61 / 30.05 / 30.03 / 31.39 / 30.03 / 30.08 s for one deployment, 60.97 / 60.06 / 60.09 s for two. Confirmed exactly as logged. |
| AUDIT-4E-4 | `weasyprint==69.0` advisory; dependency gate failing | **Critical** | **Critical** | **Not bumped, and the gate went from 1 advisory to 12 across 3 packages**: `weasyprint 69.0` (PYSEC-2026-3940), `pyjwt 2.13.0` x10 (all fix 2.14.0), `oauthlib 3.3.1` (CVE-2026-49265; reachable only via `apprise -> requests-oauthlib`, and **zero** repo code imports either, so unreachable from Wardress). |
| AUDIT-4E-5 | Every runtime image is a floating tag | Medium | Medium | **And the worker's MiniLM weights are an unpinned floating model reference** whose pre-download failure is swallowed by `|| echo` at build time — so a changed upstream revision or a failed download produces a *successful* build with different (or missing) detection semantics. |
| AUDIT-4E-6 / -4E-7 / -4E-9 | Ollama default endpoint; pull stream with no deadline; dependency hygiene residue | Low | Low | All three confirmed unchanged. |
| AUDIT-4E-8 | Heuristic redaction leaks a short custom-endpoint key | Medium | **High** (escalated) | **The leak is constructed end-to-end and reaches a Viewer**: a 9-character key survives into the dict persisted as layer-8 `ScanFinding.evidence`, and into an HTTP 503 body. The prior finding scoped the exposure to server logs + admin-only `validation_detail`; it is materially wider. |
| AUDIT-4E-10 | Two moderate frontend dev-dependency advisories below the gate | Low | **High** (escalated) | **The gate status changed**: `pnpm audit --audit-level high` is now **exit 1** with **2 HIGH `undici`** advisories (`. > vitest > jsdom > undici`), not "2 moderate, exit 0". |
| AUDIT-4E-11 | `ruff format --check .` fails and masks later CI gates | Medium | Medium | **Worse than logged**: `ruff check .` now fails on the **first** command of the backend job (9 errors at HEAD), so `ruff format --check`, `pip-audit`, `check_torch_osv` and `pytest` never execute at all. Signal masking is total, not partial. |
| AUDIT-4F-5 (detection cross-ref) | `fusion.py:40` and `:192` assert 0.35 against the real 0.40 | Low | Low | Confirmed. **Extended by a repo-wide sweep of every numeric claim in a comment across `worker/`**, which found two further drifted claims: `scan_tasks.py:48`'s "(~0.03)" benign-risk figure is now **~7x too low** (measured band 0.19–0.22), and `metadata.py`'s / `signatures.py`'s docstring claims about security-header downgrades and new-text-only lexicons are **substantively false** (6 of 8 CSP relaxations score 0.0; 7 of 9 adversarial shapes make 100% of the page "new"). One claim was **verified exact**: `scan_tasks.py:58`'s "min observed: 0.0518" reproduces from the artifact. |

---

#### New Findings

> 45 new findings. Full evidence blocks (method, repro steps, measured numbers, cross-subsystem notes, dead-code tables, optimization tables) live in the five scratch reports cited at the top of this entry. Each block below carries ID, severity, subsystem, evidence anchor, root cause and remedy category per §6.1.

##### Critical — 1 new

**AUDIT-SA1-1 — The Playwright SSRF route guard is `page.route`-scoped: Service Workers and `window.open()` popups bypass SSRF validation completely, and the bypass is not limited to the same origin**
- **Severity**: **Critical** (automatic per Rule 12 and §6.4's SSRF bullet). No inflation — the bypass is proven by **server-side truth**, not by argument.
- **Subsystem**: `worker/fetcher.py:287-340` (`_make_ssrf_route_guard`; docstring at :288-291 claims it validates "every request the page initiates"), `:543` (`page.route("**/*", ...)` — **page** scope, not context scope), `:518-525` (`browser.new_context(...)` — no `service_workers="block"`); the same claim is restated by `banner_dismiss.py:30-32` and `stealth.py:37-41`.
- **Evidence**: 3 passes, 3/3 byte-identical, real Chromium, local fixtures, truth source = the internal server's own request counter:

  | Arm | config | guard saw the internal URL? | **internal server received the request?** | body readable back by the hostile page? |
  |---|---|---|---|---|
  | **Q1 = PRODUCTION** | `page.route` + `service_workers='allow'` | **No** | **YES** (`['/secret']`) | **YES** — full secret body |
  | Q2 | `context.route` + `allow` | Yes | **YES** (abort did not stop it) | No |
  | Q3 | `page.route` + `service_workers='block'` | No | **No** (`[]`) | n/a — SW never registers |
  | Q4 | `context.route` + `block` | No | **No** (`[]`) | n/a |
  | **Popups** | `page.route` (production shape) + `window.open()` | **No** | **YES** (`['/secret?via=popup']`) | — |

  Read-back is **full**, not blind: both an `Access-Control-Allow-Origin: *` internal service and a CORS-strict (Redis/Postgres-shaped) one returned the complete secret, and the hostile page wrote it into the DOM — so it lands in the very string `fetcher.py:649` persists. **The exfiltrated internal response becomes Wardress's stored `page.html` artifact**, downloadable through the artifacts API. `docker-compose.yml` puts app/worker/beat/db/redis on one default network.
- **Root cause**: the guard delivers *page-scoped request interception*, not context-scoped enforcement; service-worker-initiated requests are reported to the routing layer but **cannot be aborted by it**, and popups are not routed at all. Three docstrings assert a coverage invariant the code does not hold. **Distinct from AUDIT-3-3**: no DNS, no TTL race, no timing luck — `window.open()` alone is a one-line trigger.
- **Proposed remedy category**: add `service_workers="block"` to `browser.new_context(...)` (proven sufficient by Q3/Q4) **and** add `context.route("**/*", guard)` for popup coverage — in addition to, not instead of, the block; add a hermetic regression test asserting **server-side zero hits** (not a browser-side `ERR_BLOCKED_BY_CLIENT`); correct the three docstrings. `app/ssrf.py` is untouched (Rule 12) — the entire fix is in `fetcher.py`'s context construction.
- **Source**: Session A cold read of the guard's request-coverage claim.

##### High — 16 new

| ID | Title | Severity | Subsystem | Evidence anchor | Remedy category |
|---|---|---|---|---|---|
| **AUDIT-SA1-2** | Non-Cloudflare bot walls are captured as real content on the **scan** path and deterministically produce false alerts | High | `worker/fetcher.py:166-201` (Cloudflare-only markers); `worker/scan_tasks.py:262-272` (**no `http_status` gate** on the scan path, contrast the baseline gate at :109-118) | Detector truth table over production `looks_like_challenge_page`: Akamai (`AkamaiGHost`, `ak_bmsc`), DataDome 403 **and its 200-OK captcha**, PerimeterX/HUMAN, AWS WAF 403 + 405 CAPTCHA, Imperva, Sucuri, 200-OK soft-block — **all pass as REAL PAGE**. End-to-end through production `run_detection` + fusion: DataDome 200 interstitial -> **risk 0.931, flagged**; Akamai 403 -> 0.917 flagged; AWS WAF 403 -> 0.927 flagged. `http_status` is carried into `PageData` and **no layer or gate reads it**. A 200-OK wall additionally bypasses the baseline `>= 400` guard, so **it can be stored as a healthy baseline** and every later scan then reads as a massive change. | Vendor-agnostic wall-page classifier (status + header/cookie/title fingerprints for Akamai/DataDome/PerimeterX/Imperva/AWS WAF + 200-OK interstitial heuristics) as a *separate* gate; an `http_status >= 400` gate on the scan path; a `blocked_page` capture-quality label. **Directly predicts Phase 5A Tier-B failures and must be fixed before them, or they will be mis-attributed to per-site flakiness.** |
| **AUDIT-SA2-1** | A rotating third-party widget (reCAPTCHA / Turnstile / Taboola / analytics / Intercom) **FLAGS** a healthy site at risk 0.6776 | High | `worker/detection/dom.py:640-676, 688-734` (layer 3) | 3 passes/shape, pstdev 0.00000. reCAPTCHA anchor iframe appears, reCAPTCHA `src` rotates, Turnstile, Taboola lazy ad iframe, Intercom, Segment, HubSpot-on-new-domain **all `flagged`**, 6 of them at exactly **0.6776** with the `new_sensitive_infrastructure` rule floor armed. Two new external stylesheets reach >= 0.50. Root cause is **not "new domain" but the absence of any notion of element identity**: layer 3 diffs *sets of URLs*, so an element already present whose `src` rotates scores identically to a brand-new injection — and `iframe_src`/`script_src`/`form_action` all carry weight 1.0. Control: the same iframe rotating *within a known domain* reads 0.19 `changed`. | Element-identity-aware ref diff (keyed on tag+position or a stable attribute, with `src`-value rotation classified separately from element addition); recalibrate the additive weights against the vendor-addition population AUDIT-2-4 measured. |
| **AUDIT-SA3-1** | The dispatcher's schedule claim is never released: a single broker blip becomes a silent one-interval scan gap | High | `worker/beat_tasks.py:160-168` (claim committed **before** any scan row exists), `:202-204` (row INSERT), `:207-213` (publish, bare `except` that only logs), `:214-221` (per-site `except` -> rollback, **no un-claim**) | Hermetic + DB-unreachable trace: with `send_task` raising, the tick returns `{'due':1,'enqueued':0,...,'lost_claim':0}` — **the complete stats key set contains no error/fail/lost-publish bucket** — the Scan row survives as `pending` with no message anywhere, and the orphan's `next_scan_at` is 1,430+ minutes out. The claim is a **schedule mutation, not an intent log**: nothing can distinguish "claimed and enqueued" from "claimed then the publish died". Note the inconsistency it creates: a concurrent `scan-now` is *self-healing* (the API's own stale-recovery path), while beat dispatch is not. | Mark the freshly-inserted `pending` row `failed` with an explicit enqueue-failure reason on the publish-failure path (it is provably never going to run); add a `lost_publish` stat counter as the minimum viable version. |
| **AUDIT-SA3-2** | No retention policy exists for scans, findings, artifacts, alerts, deliveries, remediation executions, or the audit log | High | absence of any deletion path in `backend/app/**`, `worker/**`, `alembic/**`, `tools/**` | Repo-wide grep for `retention|prune|purge|delete(Scan)|older_than|max_scans|keep_last|TRUNCATE` returns **zero** hits in any orchestration module. The only artifact deleter keys on row absence; `AuditLog` is immutable by design with no stated horizon. Monotonic growth of both the database and a mounted volume, on a product whose entire premise is unattended operation for months. Cross-confirms AUDIT-3-4's retention half from the orchestration side. | Time-bounded retention policies per table with a documented default horizon; an operator-visible "data retention" section; a scheduled prune task with per-run budgets. |
| **AUDIT-SA3-3** | A failed capture orphans its artifacts permanently | High | `worker/beat_tasks.py:271-291` (janitor keys on row existence), `worker/artifacts.py` | Hermetic: a `failed` row's artifact tree survives every janitor cycle; a row-less tree is removed (positive control). Independent confirmation of AUDIT-3-4's retention half from the janitor's side. | Janitor scope keyed on row *state* and age, not existence alone. |
| **AUDIT-SA3-4** | The worker's broker publish has no fail-fast bound: 10.7 s on the first failure, 63.8 s on every subsequent one | High | `worker/celery_app.py` (`broker_transport_options={}`, `max_retries=100`) vs `app/tasks.py` (API client: `max_retries=2, interval_start=0.1`) | Measured against a refused broker. Consequence: a worker publishing a follow-up task during a broker outage blocks a scan child for up to ~64 s per call, against a 420 s soft / 480 s hard limit — turning an infrastructure blip into wasted scan capacity and soft-time-limit kills. | Give the worker's publisher the same bounded retry policy as the API client, or make publishing non-blocking with the message handed to a retry queue. |
| **AUDIT-SA4-1** | A password reset does not invalidate outstanding access tokens and does not revoke the account's API keys | Medium→**escalated rationale** (kept Medium) | `app/routers/users.py:123-125`, `app/deps.py:53-79`, `app/config.py:43-48` | HTTP probe: after an admin password reset, the victim's **old access token -> 200**, **API key -> 200**, live refresh cookie -> 401. Exactly one of three credential classes dies. API keys survive **indefinitely** (`_user_from_api_key` checks only `revoked_at is None` and `is_active`). The asymmetry is visible in the code: `users.py:90-101` revokes refresh tokens on *role change* precisely because "role rides in the access token" — the password branch applies the same revocation and leaves the key untouched. There is no `auth_version` column anywhere. `is_active=False` does kill both classes, so deactivate/re-activate is the only working eviction today. | A `token_version` / `auth_version` column stamped into the access token and checked on every decode, plus API-key revocation on password change and on role change; a documented "log out everywhere". |
| **AUDIT-SA4-2** | The per-IP rate limiter is fully bypassable by a client-supplied `X-Forwarded-For` under the *documented* proxy configuration, and IPv6 is not normalised | Medium | `app/ratelimit.py:98-106, 117-136`, `app/config.py:88-91`, `README.md:355`, `docs/configuration.mdx:71` | Measured with the flag both ways. `TRUST_PROXY_HEADERS=true` + rotating XFF -> **8/8 allowed, limit fully bypassed** (default `false` correctly ignores it). The bug is the classic one: `split(",")[0]` takes the **leftmost** entry — the client-supplied one — while nginx `$proxy_add_x_forwarded_for` *appends* the real peer to the right. **Neither `README.md` nor `docs/configuration.mdx` says the proxy must overwrite rather than append.** Config-independent second vector: 6 addresses in one IPv6 /64 -> **6/6 allowed** from the socket peer alone. Bypassing `client_ip()` voids the dedicated login limiter too. Verified **not** findings: no fail-open mode in the limiter; the N-workers bypass is unreachable in the shipped topology (single uvicorn process, no `command:` override); API-key rotation does not reset the budget; `Retry-After` is correct. | Take the **rightmost** untrusted hop (walk the list right-to-left against a trusted-proxy count); normalise IPv6 to its /64; document the overwrite requirement next to the flag. |
| **AUDIT-SA4-3** | The per-account login lockout is an unauthenticated, effectively permanent DoS against any known account address | Medium | `app/routers/auth.py:49-51, 89-132, 160-172` | HTTP probe, unauthenticated: 9 wrong-password attempts with **no credential** -> `[401 x5, 429 x4]`; the **correct** password while locked also returns 429 with the same `Retry-After`. Back-off is `60 * 2**(count−5)` capped at 900 s, so **one request per 15 minutes — four per hour — holds the lock indefinitely at zero cost**. The legitimate admin **cannot break it by logging in** (rejected before password verification); only waiting out a window the attacker keeps re-tripping, or an admin action requiring a **second** admin. On a one-admin self-hosted install that is a hard outage with no self-service recovery. Compounds with AUDIT-SA4-2. | A cap on *total* lockout duration, operator notification on lockout, and a single-admin recovery path; consider an admin-scoped "unlock" action. |
| **AUDIT-SA4-5** | `CORS_ALLOWED_ORIGINS=*` makes the API reflect **any** origin with `Access-Control-Allow-Credentials: true`, contradicting the stated contract | Medium | `app/config.py:92-99` (`cors_origins()` validates nothing), `app/main.py:225-237` (`allow_credentials=True`) | In-process with `CORS_ALLOWED_ORIGINS=*`: simple GET and preflight OPTIONS from `https://evil.test` both return `ACAO: https://evil.test` + `ACAC: true`, `Allow-Methods: DELETE, GET, …`. Impact is currently **nil** (the only cookie is `SameSite=strict`; the bearer lives in JS module memory), which is exactly why every cross-origin mutation probe returns 401 — the entire remaining protection of the credential model rests on a cookie attribute in a different file with no assertion guarding the combination. The **default is safe**: empty origins means the middleware is not registered at all. | Reject `*` at config-parse time (or downgrade it to a non-credentialed wildcard with a logged warning); document that `*` is "any origin, with credentials", not a safe wildcard; add a test asserting the safe default. |
| **AUDIT-SA4-8** | `GET /api/sites` is unbounded and silently ignores `limit`/`offset`: 600 sites = 364,581 bytes in one response | Medium | `app/routers/sites.py::list_sites` | Measured. Bulk import admits 500 sites per call, so the list endpoint's unbounded eager baseline-summary join is reachable by design. Quantifies AUDIT-4C's own "paginate `GET /api/sites`" opportunity. | Offset/limit + total, copying the contract the alerts/scans/audit pages already implement. |
| **AUDIT-SA4-9** | `GET /api/health` returns HTTP **200** in both the healthy and the database-down branch, so status-code-based probes report healthy through a total DB outage | Medium | `app/routers/health.py` readiness route | Live + hermetic. This is the concrete form of AUDIT-4C-5's residual note, and it means `docker-compose.yml`'s style of status-code health probe would not detect a database failure. | Return 503 on the degraded branch (or document that `/live` is the only probe target and stop advertising `/health` as one). |
| **AUDIT-SA5-1** | The locked `pyjwt==2.13.0` carries 10 published advisories; one is **live-reachable as an unauthenticated HTTP 500** | High | `app/security.py` (`decode_access_token`) | **Live-proven on the shipped uvicorn+httptools image**: one 27 KB `Authorization` header (a nested JWT header) -> `RecursionError` escapes `except jwt.PyJWTError` -> **HTTP 500 with a traceback, unauthenticated**. The other 9 are unreachable (single-alg HS256, no PyJWK) — triaged individually, not waved away. Fix is 2.14.0. | Dependency bump to `pyjwt>=2.14.0`; **and** harden `decode_access_token` against non-`PyJWTError` exceptions (a token is untrusted input) so no future advisory becomes an unauthenticated 500. |
| **AUDIT-4E-8 → escalated** | *(see Confirmed table above — Medium to **High**: the leak reaches a Viewer through layer-8 `ScanFinding.evidence` and an HTTP 503 body)* | High | `app/llm.py:60-79`, `worker/detection/semantics.py` evidence, `app/routers/settings.py` | | Value-aware redaction against the configured key set, not just shape heuristics. |
| **AUDIT-4E-10 → escalated** | *(see Confirmed table above — Low to **High**: the gate is now exit 1 with 2 HIGH `undici`, and the `walkthrough/` tree has **no audit gate at all**)* | High | `frontend/package.json` (`vitest ^4.1.10`), `walkthrough/package.json` | | Bump `vitest` to >= 4.1.11; add the same `pnpm audit` gate to the `walkthrough` workflow. |
| **AUDIT-4E-1 → deepened** | *(see Confirmed table — a **third** unvalidated SSRF reader exists, and the type-keyed private-network allowance reaches cloud metadata)* | Critical | `app/llm.py` / `app/ai_ollama.py` (`/api/show`) | | Validate at the single point a `base_url` becomes a litellm deployment. |
| **AUDIT-4E-4 → deepened** | *(see Confirmed table — 12 advisories across 3 packages, not 1)* | Critical | `backend/pyproject.toml`, `uv.lock` | | |

##### Medium — 13 new

| ID | Title | Subsystem | Evidence / root cause | Remedy category |
|---|---|---|---|---|
| **AUDIT-SA1-4** | `apply_stealth` fails open only when the package is *absent*; a raising `playwright-stealth` escapes `fetch_page` and strands the scan row in `running` | `worker/stealth.py:232-243` (no try around `Stealth(...)`/`apply_stealth_async`), `worker/fetcher.py:529, 465-494` (no bare `except`), `worker/scan_tasks.py:263-272` | Live probe: `RuntimeError` propagates and state is **partially applied** (library init scripts registered, `stealth.py`'s supplementary script never lands) — a *less* stealthed state than either contract describes. `fetch_page` has no last-resort handler, so the row committed `running` at `scan_tasks.py:258-260` is never updated; no error, no alert, no evidence — a silent stall. | Extend the fail-open contract to a *raising* library (log + continue unhardened, still install the supplementary script); give `fetch_page` a last-resort `except Exception -> FetchError`. |
| **AUDIT-SA2-4** | The committed dataset's `sanity_benign_quiet` row fuses to 0.6583, and **layer 8 alone can never reach the material bar** | `worker/detection/training/fusion_dataset.json`, `worker/detection/fusion.py:62-71` | The single-layer reachability map (the operationally important artifact of Session A): `sum(c*v) = 5.8416` reaches 0.40; layers **1, 2, 3, 6, 8 are individually incapable** of it (layer 8 at its maximum of 1.0 produces only **0.1198** — a page whose entire visible content is replaced scores *lower* than one with a rotating third-party iframe at 0.6776). 8 layers uniformly at 0.0848 lands at exactly 0.4000; at 0.10 they flag with no single layer alarming. Layer 4's coefficient (26.26) is 6x layer 2's — the system's sensitivity is set by one channel. `sanity_benign_quiet`, a *calibration sanity row*, is above the flag threshold. | Re-derive `MATERIAL_CHANGE_RISK` from a benign population that includes the omitted axes; give layer 8 a channel that can carry a total content takeover; add the reachability map as a standing assertion. |
| **AUDIT-SA3-5** | A failing `_schedule_next` silently converts a site into a once-per-tick scan loop | `worker/scan_tasks.py` (swallow-all wrapper), `app/scanning.py` | Hermetic: the scan completes, the schedule is untouched, and the **next tick re-dispatches the same site** — so a persistent `_schedule_next` failure means every site with that condition is scanned every 60 s. | Surface scheduling failures as a stat/alert rather than a bare log; make the wrapper fall back to a default interval. |
| **AUDIT-SA3-6** | The in-flight unique index firing inside the dispatcher is absorbed into no stats bucket | `worker/beat_tasks.py` (dispatcher's `IntegrityError` catch), `app/models.py` partial index | A deterministically-won arbiter collision lands in `lost_claim=0` and no error bucket — so the dispatcher's own counters under-report contention. | Route the violation into a named stat (`skipped_inflight_race`). |
| **AUDIT-SA3-7** | `beat` declares no `depends_on: db`; neither `worker` nor `beat` has a healthcheck | `docker-compose.yml:118-131` | `beat` genuinely needs `DATABASE_URL` and imports `worker.db`. Independently confirmed by the AI/infra subagent. | Add `depends_on: db: condition: service_healthy` and a healthcheck to both services. |
| **AUDIT-SA3-8** | Migrations run only from `install.ps1` / `update.ps1`, never at container start | `scripts/*.ps1`, `backend/Dockerfile.app` | A container started by any other route (`docker compose run`, a scale-out, a CI job, an operator's manual `docker start` after a volume restore) comes up against an **un-migrated schema**. | Run `alembic upgrade head` as the app's entrypoint (or a dedicated migrate service the app depends on). |
| **AUDIT-SA4-2 → SA4-4 companion** | The account lockout is a user-enumeration oracle, defeating the deliberately-added constant-time dummy hash | `app/routers/auth.py:38-40, 144-172` | Same 9-request burst against both address kinds: registered -> `[401 x5, 429 x4]`; unregistered -> `[401] x9`, never 429. The **401 -> 429 transition after exactly 5 requests is a perfect existence oracle requiring 6 requests and no timing analysis**. The timing defense itself is genuinely well-built (`_DUMMY_HASH` computed at import, `verify_password` on both branches) — it is defeated by the *state* the two paths leave behind. A second leak in the same area: the unknown-account path writes an `auth.login_failed` audit row while the locked path writes **none**, so the enumeration is visible through the admin audit log too. | Increment a lockout counter for unknown addresses as well, or return a fixed-shape 429 for both. |
| **AUDIT-SA4-6** | Zero `aria-live` / `role="status"` regions anywhere in `src/`: polling state changes are never announced | `frontend/src/pages/{site-detail,health,alerts,remediation,scan-detail}.tsx` | Measured: zero live regions in the whole SPA, on surfaces whose entire purpose is asynchronous state change (2 s and 5 s poll intervals). Degrades gracefully. | A shared `<StatusAnnouncer>` on the polling surfaces; `role="status"` on verdict/degraded transitions. |
| **AUDIT-SA4-7** | Keyboard users cannot use the bulk-import CSV control; three `<Label>` elements label nothing, and no data table in the app has a caption | `frontend/src/pages/bulk-import-dialog.tsx` + tables | Measured via keyboard traversal. Compounds AUDIT-4F-7 (unnamed `role="application"`) into a systemic a11y pattern: controls and data regions exist without accessible names. | Focusable file input (or a labelled trigger button); associate every `<Label>` with a control; `<caption>` (or `aria-label`) on every data table. |
| **AUDIT-SA3-10** | `missing-prereqs` is the only scan-failure path that leaves `verdict` NULL | `worker/scan_tasks.py` | A scan row in that state renders differently from every other failure; FK cascade behaviour during concurrent delete + completion verified clean in all three orderings (positive result). | Normalise the terminal state (a typed failure reason) or handle NULL in the API/UI contract. |
| **AUDIT-SA3-11** | `pool_pre_ping=True` in `worker/db.py` is unreachable, and every Celery task pays ~88 ms to build and tear down an engine | `worker/db.py::task_session` | `task_session` builds a **distinct engine per call**, so `pre_ping` never fires, `recycle=-1` never triggers, and the pool is never reused: measured **87.4 ms fresh vs 6.9 ms pooled**. A module-scoped lazily-created engine (or a `NullPool`-free shared pool) would remove the per-task cost. *Positive result recorded too*: connection-pool exhaustion is **unreachable** at 27/100 connections with 12 workers. | A process-scoped engine with a real pool; keep `pre_ping` (it is the right defence once the pool is shared). |
| **AUDIT-SA5-3** | There is no Fernet key ring, version prefix, or re-encrypt path: rotating `CREDENTIALS_ENCRYPTION_KEY` silently destroys every stored credential, and the AI layer degrades to **unauthenticated** requests | `app/crypto.py`, every decrypt caller, `app/llm.py::_deployments` | Hermetic probe: encrypt under key A, swap to key B, and after the change `_deployments` builds a deployment with **no `api_key`** — i.e. the system does not fail, it *silently keeps working against a provider with no credential*. SMTP and Telegram channel configs are silently unconfigured by the same rotation. `.env.example` documents the key's existence but not its rotation consequence. | A versioned key ring (`FERNET_KEYS` with an active index) plus a re-encrypt migration path; a startup assertion that an unreadable blob fails the deployment rather than degrading it silently. |
| **AUDIT-SA5-4** | CI never builds either Dockerfile, and the deployed `walkthrough/` tree has no audit, lint, typecheck or test gate | `.github/workflows/ci.yml`, `static.yml`, both Dockerfiles | **Neither runtime image is built in CI at all** — so the artifacts that actually ship are unscanned by any gate, and `|| echo` in the worker's MiniLM pre-download turns a failed model download into a successful build. `walkthrough/` is a second, entirely ungated dependency tree that `static.yml` publishes. | A build-and-scan job for both images; extend the frontend gate set to `walkthrough/`; fail the build on a model-download failure. |

##### Low — 15 new

| ID | Title | Subsystem | Evidence | Remedy category |
|---|---|---|---|---|
| **AUDIT-SA1-3** | `dismiss_banners` burns its entire 3 s budget on every capture of a banner-free page | `worker/banner_dismiss.py:398-406` | Measured 3.141 / 3.093 / 3.094 s (spread 0.048 s) at 30 attempts per frame, on top of **30 CDP `query_selector` round-trips per frame**. Against a measured 10.42–11.06 s end-to-end capture of the same banner-free page, that is **~28 % of total capture wall clock**. The wasted work is invisible — `attempts` is recorded and read by nothing. | Make the late-banner wait event-driven (a single cheap probe or a `MutationObserver`) rather than a flat timeout; skip it when the combined selector set is provably absent. |
| **AUDIT-SA1-5** | The screenshot guard is dimension-asymmetric: it caps height only, and the evidence cannot express width | `worker/fetcher.py:377-416, 395`; `worker/stealth.py:92-99` | Measured: a 40,016 px page caps correctly to 1366x16384 with a valid `IEND`; a **20,008 px-wide** page captures **uncapped** at `screenshot_capped: False`, `capture_quality: "full"`, evidence `actual_height: 768` with **no width key at all**. Chromium's raster/tile limit is square; only the vertical axis is guarded. No failure was produced on this headless software-rasterised host, so no corruption is claimed. | Probe and cap width symmetrically; add `actual_width` to evidence; classify as degraded when either dimension exceeds the limit. |
| **AUDIT-SA3-9** | `via` is accepted and silently discarded by the three orchestration service functions | `app/services.py` | Code trace. The parameter exists on three service functions and no caller uses it. | Remove the parameter or wire it into the audit snapshot. |
| **AUDIT-SA3-12** | `wardress.ping` is an orphan task registration, and every task result is stored in Redis for 24 h for a consumer that does not exist | `worker/celery_app.py` | No production caller; Celery result retention bounded at 24 h and nothing reads results. | Deregister the task; set `result_expires` to the shortest workable value or disable the backend if unread. |
| **AUDIT-SA3-13** | Redis runs with no AOF and no `maxmemory`: a restart loses in-flight queue messages, and growth is unbounded | `docker-compose.yml:23-32` | Live inspection. Compounds AUDIT-SA3-2: the broker's memory grows with no ceiling while the database grows with no ceiling, on the same self-hosted premise. | Enable AOF (or document the loss window explicitly); set a `maxmemory` policy; state the restart semantics in the install docs. |
| **AUDIT-SA4-10** | Twelve provably-dead client functions in `src/lib/api.ts` leave eleven admin routes as live write surfaces with no caller, several advertised as `DEPRECATED` in the public schema | `frontend/src/lib/api.ts`, `app/routers/{settings,users}.py` | Grep-proven dead. Also a **functional gap**: there is no UI path to edit an existing AI provider. | Make the twelve live or absent; retire the deprecated backend routes alongside. |
| **AUDIT-SA4-11** | The initial JS payload is 1,077 kB / 404 kB gzip; a route-level `lazy()` split measures 268 kB / 83 kB gzip | `frontend/` | Sourcemap-level byte attribution: 205 kB is inlined provider logos and 146 kB is Markdown machinery for 2 of 10 routes. | Route-level `lazy()` (measured −809 kB raw / −321 kB gzip); move provider logos behind the settings route. |
| **AUDIT-SA4-12** | The audit-log `actor` filter treats `%` and `_` as LIKE wildcards | `app/routers/audit.py:38-39` | Measured: `actor=%` matches every row. Admin-only read filter, correctness not security. | Escape `%`/`_`/`\` before interpolation. |
| **AUDIT-SA4-13** | Four dead symbols and one duplicated predicate: the JWT `role` claim, `AnyRoleUser`, `TableCaption`, two unused response fields, and the degraded predicate copied into two routers | `backend/app/security.py`, `frontend/src/lib/api.ts`, routers | Grep-proven. The duplicated degraded predicate is the interesting one: two routers each carry their own copy of the same `_has_degraded_layer` logic. | Remove; extract the shared predicate. |
| **AUDIT-SA5-2** | `litellm` logs the full LLM prompt and the full raw response in plaintext at DEBUG; `app/llm.py` sets three litellm globals but never `turn_off_message_logging` | `app/llm.py`, litellm 1.93.0 | Probe drove production `_build_router(...).acompletion` against a fake endpoint with DEBUG logging: 96 records captured, **0 containing the API key** (so the key is safe) but the **prompt and reply bodies are in full**. The escalation prompt is built from **raw, un-normalized, un-suppressed HTML**, so it can contain captured page content verbatim. | Set `turn_off_message_logging = True` (or `litellm.suppress_debug_info` + an explicit logging filter); redact evidence text at the prompt boundary. |
| **AUDIT-SA5-5** | `.dockerignore` excludes git-tracked ignores, so local scratch logs are baked into the shipped `wardress-app` image | `.dockerignore`, `Dockerfile.app` | Live: `build_app.err.log` and `build_app.log` are present in the image, absent from git, and absent from `.dockerignore`. | Invert the pattern (ignore everything, re-include the build context) or drop `.gitignore` from `.dockerignore`'s source list. |
| **AUDIT-SA5-6** | Both runtime images run as root, and the compose services set no `security_opt`, `cap_drop`, `read_only` or `user` | both Dockerfiles, `docker-compose.yml` | Read-only inspection. Given AUDIT-SA1-1's SSRF-reach finding, a root capture container with a default network is the relevant multiplier. | Non-root `USER`, `cap_drop: [ALL]`, `no-new-privileges`, `read_only` where feasible. |
| **AUDIT-SA5-7** | `LOGIN_RATE_LIMIT_PER_IP` is read by the code, exercised by tests, and documented in **neither** `.env.example` **nor** `docker-compose.yml` | `app/config.py:86` -> `app/ratelimit.py` | The env-var cross-reference (every `os.getenv` / pydantic-settings field in `backend/` and every `process.env` in `frontend/` diffed against both files) found exactly **1 gap, 0 documented-but-unread, and 1 deliberate correctly-documented exclusion (`ARTIFACTS_DIR`)**. This is the *tightest* security knob in the system and it is untunable and undocumented. | Document and forward it. |
| **AUDIT-SA5-8** | `actions/checkout` leaves `persist-credentials` at its default in all three workflows | `.github/workflows/{ci,static}.yml` | Read-only inspection. No `pull_request_target` trigger and no write scope were found (both verified clean), so the exposure is narrow. | Set `persist-credentials: false` explicitly. |
| **AUDIT-SA5-6b** | Alert delivery has no retry at all under a provider outage, and no circuit breaker | `worker/alert_tasks.py`, `worker/beat_tasks.py` (resweep cadence) | Model: under an SMTP outage the only retry is the 5-minute resweep, up to 200/run, with no backoff and no breaker. *Positive contrast recorded*: this is the opposite failure direction to AUDIT-4D-1/4D-2 (which lose alerts) — it is over-*work*, not loss. | Exponential backoff on the resweep predicate; a per-channel breaker; a `skipped` terminal row (which also closes AUDIT-4D-6). |
| **AUDIT-SA5-7b** | Remediation webhook payloads carry no authentication and no replay protection | `app/remediation.py::post_webhook` | A receiver has no way to authenticate the sender or dedupe a retry. Compounds AUDIT-2B-3's accepted at-least-once residue: the lease-reclaim path re-POSTs without knowing whether the first landed, and `scan.id` is the only dedupe handle. | A shared-secret HMAC header or an `Idempotency-Key`; document the retry semantics. |

---

#### Invalidated Findings

- **AUDIT-4B-8 (deployment drift) — INVALIDATED (file-drift half).** Re-verified by three independent subagents with `docker cp` + `git hash-object`: **20/20 MATCH** (orchestration scope), **10/10 MATCH** (API/frontend scope), **27/27 MATCH** (AI/infra scope) — 57 file comparisons, zero mismatches, CRLF-normalised on both sides. `worker/scan_tasks.py`, the file 4B reported as differing, is now `a6878b37...` in the container — byte-identical to the exact HEAD value 4B itself recorded. HEAD = `701552e`, working tree clean. **Consequences**: (a) 4B's "rebuild from HEAD before remediation-phase verification" hard requirement is **already satisfied** and can be dropped; (b) 4B's mixed-build caveat no longer applies, so every 4B live probe is now attested against the code it describes; (c) **the finding's substance survives as a Low residual** — nothing records which commit an image was built from, which is how the drift went undetected in the first place, and the beat schedule file (`/app/celerybeat-schedule.db`, 12,288 B, `PersistentScheduler`) still lives in the container's writable layer with no volume, so it is lost on container recreate (benign by construction — every periodic task is idempotent — but undocumented).
- **AUDIT-4C-2's "`wk_` key prefix in the public schema" — INVALIDATED (partial).** 0 hits across the 99,585-byte OpenAPI document; the prefix lives in `app/apikeys.py`, not in the published schema. The finding itself stands on 8 stronger items (including the newly-found `/docs/oauth2-redirect` route and the schema's narration of the SSRF gate).
- **Two Session A hypotheses tested and rejected in capture** (recorded so they are not re-audited): (a) an **IDN hostname does not** break the consent-cookie batch — Chromium accepts both the unicode and punycode forms, 13/13 cookies; (b) the screenshot height cap **cannot** produce a corrupt PNG — a 40,016 px page caps to 1366x16384 with a valid `IEND` (307,719 B), and a raw uncapped 40,016 px render also succeeds.
- **One Session A hypothesis tested and rejected in detection**: `layer1 = 1.0` + real-Chromium render noise does **not** false-flag. Measured with 5 full-page renders at 1366x3442 over 12 pairs: layer 4 = 0.0001 / 0.0001 / 0.0001 / 0.0024, mean **0.0012**, pstdev 0.00115, max 0.0024, SSIM 0.9999 — **18x below the 0.2225 escalation bar**, and PNG byte sizes varied only 0.25 % with zero dimension change. Layer 4's 26.26 coefficient is **defensible for static pages**; the interactive-page question is routed to Phase 8.

---

#### Cross-Subsystem Interactions

Ten interaction clusters were identified. The first three are, in the coordinator's assessment, the material output of Session A — each is a single defect class that the phase-by-phase structure could not have seen because it lives on a seam.

**XS-1 — "Degradation is invisible end-to-end": six findings, one chain, one fix shape.**
`worker/fetcher.py` computes 17 of 19 `capture_evidence` keys and **nothing reads them** (AUDIT-3-5) -> `ScanPageData(...)` drops the whole dict at the constructor (AUDIT-3-5) -> `ScanFinding` has no `degraded` column, so a findings-only consumer cannot tell "provably zero" from "dark channel" (AUDIT-2-5) -> `pipeline.py`'s degraded guard is baseline-side only, and an *empty page pair* inverts the system's own "provably zero vs unmeasured" distinction (AUDIT-4-5) -> `routers/sites.py` counts degradation fleet-wide but the site-detail payload's TS type drops the `degraded` key and `consecutive_degraded_scans` is read by **zero** files (AUDIT-4F-2) -> the UI renders `Clean` / green dot / `0%` / `0/1 layers ran` while the Health page simultaneously counts the site under "Degraded Captures". **A scan that measured nothing and a scan that measured identical are the same object to every operator-facing surface.** Six findings, one chain.

**XS-2 — The SSRF policy is applied per call site rather than structurally: five instances across four subsystems, one fix.**
AUDIT-SA1-1 (Critical — the browser's page-scoped route guard, with full read-back into a stored artifact) + AUDIT-4E-1 (Critical — three AI reader paths, one of which is newly found) + AUDIT-4E-2 (Critical — the catalog fetch, plus a "never raises" contract that a schema violation falsifies) + AUDIT-4D-3 (the favicon resolver) + AUDIT-4E-2b's unpinned-client class shared with `probe.py`. All are the same shape: *someone remembered to add the check*. AUDIT-SA1-1 additionally proves the browser arm needs a context-level change (`service_workers="block"`), not just a route-scope change — so the fix is a shared outbound-fetch factory **plus** an armoured capture context. AUDIT-4E-1's finding that the private-network allowance is keyed on provider *type* and therefore reaches cloud-metadata addresses means the allowance itself, not just its application, needs review.

**XS-3 — Detection-to-notification has three independent, silent, unrecoverable loss windows.**
AUDIT-4B-1 (alert row creation after the terminal commit, measured at **10.1 ms median / 26.8 ms max**, plus an unbounded DB-hiccup variant that is ACKed rather than redelivered) + AUDIT-4D-1 (per-channel commits during delivery; **now deterministically reachable from a CR/LF in a user-controlled site name**, real window `40 s x (channels−1)`) + AUDIT-4D-2 (check-then-act guard double-sends). All three are silent, all three are covered by exactly the wrong recovery primitive, and none of the three is covered by the `resweep_undelivered` task — whose predicate is "zero delivery rows" while creation failures leave *no row at all*. Detection → notification is the system's core output.

**XS-4 — Retention is unbounded in every store the product writes to.**
AUDIT-3-4/SA3-3 (artifact directories whose rows still exist survive forever; nothing ever deletes a `Scan` or `Baseline` row) + AUDIT-SA3-2 (scans, findings, alerts, deliveries, remediation executions, audit log) + AUDIT-SA3-13 (Redis with no `maxmemory` and no AOF) + AUDIT-SA5-5 (scratch logs baked into the shipped image). The deployment premise is unattended, self-hosted, months-long operation.

**XS-5 — False positives on healthy sites are the dominant real-world risk, and they arrive from three independent directions.**
(A) *Capture failure*: AUDIT-SA1-2 (bot-wall pages -> risk 0.917–0.931, `flagged`), AUDIT-3-1 (a banner click can capture the wrong page and defeat the challenge gate), AUDIT-3-4 (a truncated artifact behind a `completed` row). (B) *Probe transients*: AUDIT-4-2 (TLS failure now fuses to **0.5502**, above the flag threshold). (C) *Detection scoring*: AUDIT-SA2-1 (a rotating widget flags at 0.6776), AUDIT-4-1 (a one-word edit on an unpunctuated page reaches **1.0**), AUDIT-2-4 (**34 of 323 benign rows in the model's own training data** exceed the default flag), AUDIT-4-5 (binary-junk capture at 0.9833). Every one of them creates an `Alert` **and** a `RemediationExecution` **and** permanently pins cadence to `base/4`. The LLM second opinion is **not** consulted for most of them (they exceed the 0.75 escalation ceiling), so the designed mitigation does not apply.

**XS-6 — False "clean" on real attack patterns: the class that most directly violates the North Star.**
AUDIT-SA2-2 (Critical — a CSP widening from `'self'` to `*` scores **exactly 0.0**; the scan reads `clean` at risk 0.0031, and the direction classifier returns "unknown" for **6 of 8** real-world relaxations while calling an attacker-added origin `stronger`) + AUDIT-SA2-3 (Critical — layer 7 is **exactly 0.0** for a cloaked banner at >= 146 reference tokens, because the additive ramp is anchored to `added/|ref|` and therefore decays as the page grows, while the *legitimate* mobile-serves-less case grades 0.62–0.66) + AUDIT-4-5 (both sides empty -> `clean`) + AUDIT-4-6 (removal-only defacement; and un-hiding a hidden spam farm -> `layer2 = 0.0` with zero structural churn) + AUDIT-2-3 (redirect and client-side cloaking) + AUDIT-SA2-4 (layer 8 at its maximum contributes only 0.1198, so a *total* content takeover is the largest miss the coefficient table encodes).

**XS-7 — CI cannot report, so every "the suite is green" claim in this log is unverifiable at the repo level.**
AUDIT-4E-11 is now **worse** than logged: `ruff check .` fails on the *first* command of the backend job, so `ruff format --check`, `pip-audit`, `check_torch_osv` and `pytest` never execute. AUDIT-4E-4/SA5-1 put `pip-audit` at 12 advisories across 3 packages. AUDIT-4E-10 escalated: the frontend gate is now **exit 1** (2 HIGH `undici`). AUDIT-SA5-4: **neither Dockerfile is built in CI at all**, and `walkthrough/` has no gate whatsoever. The only green security-relevant gates are `check_torch_osv` and `alembic check`.

**XS-8 — Both "recovery actions" an operator would reach for do not do what the API implies.**
AUDIT-SA4-1 (a password reset revokes refresh tokens only; access tokens and API keys survive indefinitely) + AUDIT-SA5-3 (rotating `CREDENTIALS_ENCRYPTION_KEY` silently destroys every stored credential and the AI layer then *keeps working against the provider with no credential at all*, while SMTP and Telegram silently unconfigure). Both are silent, both are one operator action away, and both defeat the documented incident-response procedure.

**XS-9 — AUDIT-SA1-2 directly predicts Session B Wave 1's Tier-B failures, and sequencing matters.**
The stress catalog's Tier B is Akamai / DataDome / PerimeterX / AWS WAF / Turnstile. Per the capture subagent's measured truth table, **every one of those vendors' walls is currently captured as real content and produces a `flagged` scan** — so Phase 5A+5B will fail those sites for a *detector* reason, not a flakiness reason, and will mis-attribute it per-site unless the wall classifier and the scan-path `http_status` gate land first. This is the one Session A finding that changes the plan for a pending phase.

**XS-10 — The dead-code / write-only surface is repo-wide, and it is concentrated in exactly the places the phases believed were complete.**
Capture: 17 of 19 `capture_evidence` keys have zero production readers, including two added *specifically* for triage (`capture_wall_clock_ms` by Phase 7, `retry_count` by Phase 6). Detection: `signatures._new_text`'s `base_lines` set proven dead by a 20,000-pair behavioural A/B (reproduced as a regression guard); `cloaking.py:117`'s `added == 0` arm proven redundant over a 400-case grid (also reproduced as a guard); `script_profile(sample_cap=)` has no production caller; `__all__` omits `degraded_result` despite 5 production importers; 6 unused generator parameters. Orchestration: `wardress.ping` is an orphan registration, `via` is accepted and dropped by three service functions. API/frontend: 12 dead client functions leaving 11 admin routes live but caller-less, plus 4 dead symbols and a duplicated degraded predicate across two routers. AI/infra: 2 orphan functions and a duplicated `LAYER_LABELS` map. **Every one of these is proven by behavioural A/B or repo-wide grep, not by inspection.**

---

#### Updated Opportunities Register

New opportunities raised by Session A (in addition to everything already logged in O-1…O-8, O-4D-1…3, O-4E-1…4):

| # | Idea | Why it would help | Where |
|---|---|---|---|
| **O-SA-1** | **One outbound-fetch factory** (extend AUDIT-4E's O-4E-1): a `safe_async_client()` that always installs the pinning transport + validates on open, **plus** a test asserting no module builds a bare `httpx.AsyncClient` for outbound work — and, for the browser, a single armoured-context constructor that both blocks service workers and installs a context-scoped guard | Makes "forgot the policy" unrepresentable across AUDIT-SA1-1, 4E-1, 4E-2 and 4D-3 at once, and turns `ssrf.py`'s docstring back into a fact | `app/ssrf_transport.py`, `worker/fetcher.py`, `ai_catalog.py`, `site_icons.py`, `ai_ollama.py`, `remediation.py`, `probe.py` |
| **O-SA-2** | **Batched MiniLM encoding** — measured **1.68x, −253 ms/scan** (24 individual `embed_text()` calls: 626.5 ms mean, pstdev 33 → 2 batched `encode()` calls: 373.6 ms, pstdev 6). Per-call overhead floor is 12.61 ms, so at the 24-chunk worst case a page pays 300–605 ms of pure overhead. Layer 8 is **959 ms of a ~1.44 s detection cost (66 %)** | The single highest-value optimization found in Session A | `worker/detection/semantics.py` |
| **O-SA-3** | **Resize each screenshot once per layer-4 call** — instrumented: 8 `resize()` + 8 `convert()` calls per invocation; `resize` alone is 0.749 s tottime over 5 invocations = **150 ms/call, 33 % of layer 4**. Deriving pHash/dHash/SSIM/chroma from one downscaled array projects **90–120 ms/scan** | Needs a corpus re-baseline (hash values shift), so it is a deliberate trade | `worker/detection/visual.py` |
| **O-SA-4** | **Event-driven banner wait** — removes **3.09–3.14 s from every capture of a banner-free page** (measured, 3 passes), which is ~28 % of a 10.4–11.1 s capture; and **scroll a consent-iframe control into view** before the viewport test, which converts a measured `dismissed: False` into a real dismissal and recovers the lazy content the overlay's scroll-lock was suppressing | The largest single capture-latency win found | `worker/banner_dismiss.py` |
| **O-SA-5** | **Parallel `probe_site` UA fetches** (`asyncio.gather`) — measured 4 sequential requests at 1.61–1.77 s; `max_connections=4` is already provisioned and idle for 3 of 4 slots | ~2x on the probe leg; must preserve `desktop_chrome`'s headers for layer 6 | `worker/probe.py` |
| **O-SA-6** | **Route-level `lazy()` in the SPA** — measured: initial payload 1,077 kB / 404 kB gzip, of which 205 kB is inlined provider logos and 146 kB is Markdown machinery for 2 of 10 routes; a route-level split measures **268 kB / 83 kB gzip** | −809 kB raw / −321 kB gzip on first load | `frontend/src/App.tsx` routing |
| **O-SA-7** | **A process-scoped DB engine for Celery tasks** — measured 87.4 ms fresh vs 6.9 ms pooled, paid on every task, while `pre_ping` sits configured-but-unreachable | Removes a per-task engine build; makes the existing pool settings meaningful | `worker/db.py` |
| **O-SA-8** | **Fernet key ring + re-encrypt migration path**, with a startup assertion that an unreadable blob fails the deployment rather than degrading it silently | Closes AUDIT-SA5-3 and makes credential rotation an operation rather than a data-loss event | `app/crypto.py`, `app/llm.py`, `app/alerting.py` |
| **O-SA-9** | **A "third verdict state"** (`clean` / `changed-benign` / `changed` / `flagged`) driven by the content-layer peak excluding `layer1` *and* the generic churn term | Directly implements what the AUDIT-1-1 measurement shows is required (the byte-hash exclusion alone does not deliver `clean`), and gives the frontend a vocabulary for the state operators actually see | `worker/scan_tasks.py`, `app/schemas.py`, `site-detail.tsx` |
| **O-SA-10** | **A `degraded`/`unmeasured` presentation vocabulary** — a shared severity module (`riskTone(value, threshold)`) plus a distinct third layer state, so a dark channel never renders with the same vocabulary as a measured zero | Closes AUDIT-4F-2, 4F-4, 4F-7, 4F-8 **and** the frontend half of XS-1 in one change; this is AUDIT-4F's own opportunity list, now with a measured justification | `frontend/src/lib/`, all capture surfaces |
| **O-SA-11** | **A build-commit marker baked into both images**, plus a CI job that actually builds and scans them | AUDIT-4B-8's drift was invisible precisely because nothing recorded the build; AUDIT-SA5-4 means the shipped artifacts are currently unscanned | `Dockerfile.*`, `ci.yml` |
| **O-SA-12** | **A standing `min-rows-per-benign-axis` assertion in the corpus validator** — adding the 6 omitted benign axes would immediately fail the build (measured maxima 0.8269 / 0.8454 / 0.3588 / 0.6583 / 0.0222 / 0.0048), which is the correct signal | Converts AUDIT-2-4's blind spot from a one-time measurement into a build-time failure | `backend/tools/build_regression_corpus.py` |
| **O-SA-13** | **A `partial_cloaking_small_payload` corpus axis across >= 3 reference sizes**, and a `layer8_total_takeover` shape | AUDIT-SA2-3 and AUDIT-SA2-4 both expose ranges with **no corpus row at all** (274 of 323 attack rows have layer 7 exactly 0.0; no partially-cloaked row exists in either artifact) | `backend/tools/build_regression_corpus.py`; feeds Phase 8's fixture suite |

**Attack-shape gaps handed to Audit Phase 8** (from the detection subagent, measured today — this is Phase 8's fixture backlog, ordered by the severity each gap currently causes):

| # | gap | measured today |
|---|---|---|
| 1 | **Benign**: reCAPTCHA / Turnstile / Taboola / Intercom / analytics / chat widget appears, or its `src` rotates | `flagged` at 0.6776, 3/3 |
| 2 | **Benign**: operator adds a legitimate vendor script (`vendor_script_added` axis) | every row flags, mean 0.7538 |
| 3 | **Benign**: a legitimate site redesign (`site_redesign` axis) | max 0.8454 |
| 4 | **Benign**: one or two new external stylesheets | 1 -> 0.4243 (cadence), 2 -> `flagged` |
| 5 | **Benign**: `sanity_benign_quiet` — the calibration sanity row itself | 0.6583 |
| 6 | **Benign**: an A/B variant swap (`ab_test_variant` axis) | max 0.3588 — the closest benign axis to the bar |
| 7 | **Attack**: a CSP widening, or `script-src 'self'` -> `'unsafe-inline'` | `clean` at 0.0031 |
| 8 | **Attack**: a maximal HSTS downgrade (2 y + includeSubDomains + preload -> `max-age=300`) | 0.1 -> risk 0.0041 |
| 9 | **Attack**: an attacker origin added to the CSP allowlist | classified `stronger`, 0.0 |
| 10 | **Attack**: a small cloaked payload on a realistic page (>= 146 reference tokens) | layer 7 = **exactly 0.0** |
| 11 | **Attack**: un-hiding a hidden spam farm (drop `style="opacity:0"`) | layer 2 = 0.0, `structural_churn = 0` |
| 12 | **Attack**: removal-only defacement (strip scripts / iframe / form / link) | layer 3 = 0.0 on all five kinds |
| 13 | **Attack**: an unpunctuated page + baseline-present lexicon + any one-word edit | `flagged` at 0.94–1.0 |
| 14 | **Attack**: single-word tampering (`two weeks` -> `two days`) | 0.1942, never escalated |
| 15 | **Attack**: `<meta http-equiv=refresh>` / client-side `location.replace` cloak | 0.1987 / 0.3153 |
| 16 | **Attack**: a same-origin credential-harvest overlay | 0.2242 (only a new-domain overlay is caught, at 0.5450) |
| 17 | **Attack**: a payload in a timed `<script>` string | 0.3153 (the DOM-*text* form of the same attack **is** caught at 1.0) |
| 18 | **Positive control needed**: an attack **withdrawn** mid-window | currently caught at 0.9976 via layer 4 — **no corpus row guards this**, so a regression would be silent |
| 19 | **Benign, needs live measurement**: a hue-only brand refresh | dataset max 0.0222, but layer 4 alone at 0.2379 flags; the synthetic hue test read 0.0, so the real `hsl()`-swap render is unmeasured |

Plus the three mandatory **visual-only** attack fixtures `NB-DET-1` §4 already mandates (Phase 8's own spec).

---

#### Regression Results

Aggregated from all five subagents plus one coordinator re-run. **Every count is from an actual run this session** (Rule 13). All backend runs used a dedicated `wardress_sa_*_test` database on the recreated `wardress-test-pg`.

| Subagent | Suite | Result |
|---|---|---|
| Coordinator | **All three new Session A test files together** (`test_phase_sa3_orchestration_deep.py`, `test_phase_sa5_ai_infra_repros.py`, `test_session_a2_detection_findings.py`) on `wardress_sa_consol_test` | **138 passed in 98.19 s** — 0 failed, 0 skipped |
| Detection | `test_session_a2_detection_findings.py` x3 | **107 passed** — 73.62 / 86.37 / 83.31 s (3/3, zero variance in the count) |
| Detection | 23 detection files + the new file | **541 passed in 322.09 s** |
| Detection | 12-file detection baseline batch (pre-existing) | **222 passed in 112.01 s** |
| Detection | 10-file detection baseline batch (pre-existing) | **212 passed in 164.13 s** |
| Detection | `ruff check` / `ruff format --check` on the new file | **All checks passed!** / **1 file already formatted** |
| Orchestration | `test_phase_sa3_orchestration_deep.py` | **22 tests, 0 failed, 0 skipped, 0 xfail** |
| Orchestration | 6 subsystem-adjacent suites | **157 passed** |
| Orchestration | Full backend suite (with concurrent subagent files present) | **1,457 passed, 10 deselected, 6 errors in 31:06** — the 6 errors are a **Windows `PYTEST_CURRENT_TEST` 32,767-char env-var ceiling hit during pytest *teardown*** by a concurrent sibling subagent's file, not a regression; **confirmed absent when the same files are run in a single session** (see the coordinator row above, 138 passed / 0 errors) |
| AI/infra | `test_phase_sa5_ai_infra_repros.py` | **9 passed in 0.38 s** |
| AI/infra | 13-file AI/delivery/SSRF batch (incl. 4E's own 21 repro tests and 4D's 5) | **250 passed, 1 warning in 181.01 s** (the warning is the pre-existing apprise `imghdr` DeprecationWarning) |
| AI/infra | `ruff check` / `ruff format --check` on the new file | **All checks passed!** / **1 file already formatted** |
| AI/infra | `alembic upgrade head` + `alembic check` on `wardress_sa_ai_test` | exit 0 / **"No new upgrade operations detected"** |
| API/frontend | 13-file API-surface regression batch | **168 passed, 1 warning in 167.30 s** |
| API/frontend | `pnpm build` | built in 6.22 s; `index-*.js` 1,103.50 kB / gzip 417.54 kB (+ the pre-existing >500 kB advisory) |
| API/frontend | `pnpm exec vitest run` x3 | **22 files / 144 tests / 0 failed, exit 0** (17.84 s / 53.16 s cold / third pass after scratch deletion) |
| API/frontend | `pnpm exec tsc -b` | **exit 0**, no output |
| API/frontend | `pnpm exec oxlint src` | **exit 0**; 12 warnings, 0 errors on 54 files (= the recorded baseline) |
| Capture | *(no repo file changed — no suite owed per Rule 5)* | `git diff --stat HEAD` empty throughout |

**Supply-chain gates executed live this session** (AI/infra subagent):

| Gate | Command | Exit | Result |
|---|---|---|---|
| Backend dependency audit | `uv run --frozen pip-audit --skip-editable` | **1** | **12 known vulnerabilities in 3 packages** (was 1): `weasyprint 69.0` (fix 70.0), `pyjwt 2.13.0` x10 (fix 2.14.0), `oauthlib 3.3.1` (unreachable — zero repo imports) |
| torch OSV cross-check | `uv run --frozen python tools/check_torch_osv.py` | **0** | torch 2.13.0: no known advisories |
| Frontend audit (CI gate) | `pnpm audit --audit-level high` | **1** | **2 HIGH `undici`** (was "2 moderate, exit 0") |
| Frontend audit (all) | `pnpm audit` | 1 | 12 total: 3 low / 7 moderate / 2 high |
| **Walkthrough audit (no CI gate exists)** | `cd walkthrough && pnpm audit --audit-level high` | **1** | **1 HIGH `nanoid`** + 6 moderate + 1 low |
| Backend lint (CI step 1) | `uv run --frozen ruff check .` | **1** | **9 errors** at HEAD — so steps 2–5 never run |
| Backend format (CI step 2) | `uv run --frozen ruff format --check .` | **1** | **24 files** (identical count to 4E) |
| Migration drift | `uv run --frozen alembic check` | **0** | no drift |
| Compose validation | `docker compose config --quiet` | 0 | green (validates nothing about the images) |

**Alembic downgrade verification (orchestration subagent — never done before, requested explicitly).** Two independent sweeps: an empty database, and a **fully populated** one (1 row seeded through the ORM into all 23 tables).

> **Verdict: all 16 migrations downgrade cleanly with zero residue, on both an empty and a fully populated database. `downgrade base` leaves only an empty `alembic_version`; `upgrade head` round-trips; `alembic check` reports no drift before and after.** No migration fails, partially fails, or leaves residue. Three *data*-destructive (not failure) notes carried forward: `0a6bd482fe1f` silently disables the absolute session-lifetime anchor on downgrade (security-relevant, undocumented); `j4k5l6m7n8p9` silently resets login-lockout state (so a downgrade re-enables brute-force attempts until the next failure); and `i3j4k5l6m7n8`'s **upgrade** deletes duplicate sites with cascade, which is the only forward-path destructiveness and is not surfaced to an operator anywhere. `g1h2i3j4k5l6`'s downgrade removes `ix_scans_one_inflight_per_site`, so between that downgrade and `k5l6m7n8p9q1`'s re-upgrade concurrent `scan-now`s can both create a scan.

**New hermetic tests added this session** (all committed-passing characterization tests per Rule 5; each asserts *current* behaviour so a remediation prompt can flip the specific assertion it fixes):

| File | Tests | Covers |
|---|---|---|
| `backend/tests/test_session_a2_detection_findings.py` | **107** (12 classes) | SA2-1 widget FPs + rule-floor arming; SA2-2 CSP widenings -> `None` -> `clean`; SA2-3 `_new_text` collapse + 5 lexicon families end-to-end; SA2-4 over-broad suppression blinding layers 5+8; SA2-5 removals + un-hiding; SA2-6 cloaking scale-blindness + the `added==0` redundancy proof; SA2-7 empty/whitespace/comment-only/binary captures; SA2-8 the 8-layer reachability map + sigmoid safety over z in [-1000,1000] + NaN->trusted-zero + fallback-floor preservation + the `base_lines` dead-code proof (4000 pairs) + the 0.0518 comment verified from the artifact; SA2-9 5 taxonomy evasion shapes + 2 positive controls + attack-withdrawal; SA2-10 13 adversarial-HTML normalization shapes; SA2-11 34 benign dataset rows flag / `vendor_script_added` mean 0.7538; SA2-12 MiniLM cosine has no finite guard + NaN -> maximal drift |
| `backend/tests/test_phase_sa3_orchestration_deep.py` | **22** | AUDIT-4B-1's window measured over 5 passes + a positive control; SA3-1 claim-not-released (2 tests); SA3-5/SA3-6; 4B-5's baseline half (a stuck pending baseline survives all 4 beat tasks) + `skipped_no_baseline` burning an interval; 4B-6's heartbeat-skipped-on-error + `expires == interval` for every periodic task; the 480 < 3600 bound for every registered task; SA3-4's publish asymmetry; SA3-11's fresh-vs-pooled engine cost; SA3-2's retention absence; SA3-3's orphaned failed-capture artifacts; concurrent delete + completion in all 3 orderings; 4B-3's cadence floor |
| `backend/tests/test_phase_sa5_ai_infra_repros.py` | **9** | SA5-1's `RecursionError` escape from `decode_access_token` + the unredacted short key reaching layer-8 evidence; 4E-1's third reader (`/api/show` never consults the policy) + the type-keyed cloud-metadata allowance + `normalize_base` passthrough; 4E-2's falsified "never raises"; 4D-1's CR/LF site-name `ValueError`; **positive control**: the alert HTML template escapes a hostile site name; SA5-3's key-ring absence + rotation degrading to keyless |
| *(none for capture)* | 0 | Deliberate: every capture finding's hermetic repro currently **fails** against production code, and Rule 5 forbids committing a red test. Five proposed failing-test files are specified in `scratch/session-a-capture.md`'s Summary with what each would prove. |
| *(none for API/frontend)* | 0 | Deliberate: SA4 added **zero** files to the repository. Three scratch vitest files were created and **deleted** (they attach `process` handlers for React-escaping errors and would have made `vitest run` exit 1 despite all tests passing — the exact trap Phase 4F documented). |

**Rule 5 status: no regression.** Every suite is at or above its recorded baseline, `git diff --stat HEAD` is empty (zero production edits across the whole session), no subagent committed, no subagent stopped/restarted/rebuilt a container, and the live stack was left clean (no throwaway users, sites, API keys, channels, conversations or hooks; every mutable operation ran against a subagent's own scratch database).

#### Log-vs-reality discrepancies (claims from prior entries that Session A could not reproduce as written)

1. **`AUDIT-4-2`'s fused risk of 0.429 is understated.** With the `layer1_hash = 1.0` any real byte-changing scan carries, the measured fused risk is **0.5502 — above the default 0.50 flag threshold**, not merely the 0.40 material bar. The logged scenario must have had a different layer-1 profile. (Severity consequence: this is a **flag**, not just a cadence event.)
2. **`AUDIT-4-3`'s "risk stays ~0.01" is understated by ~50x.** Measured with a statically-expired cert on both sides: layer 6 = 0.5, **fused risk 0.4857**, verdict `changed` forever, and permanently inside the LLM escalation band (0.40 <= 0.4857 < 0.75) — **an LLM call per scan** plus a permanent `base/4` cadence pin.
3. **`AUDIT-4-4`'s cost claim is unreachable.** "A rule that times out only on long nodes can burn nodes x 2 s before its first timeout" — measured: 60 pathological nodes under one timing-out rule cost **2.00 s total**, because the `TimeoutError` aborts the whole element loop at the first node. The asymmetry half is confirmed.
4. **`AUDIT-1-1`'s proposed remedy would not achieve its stated goal.** Phase 1 proposed excluding the raw byte-hash from the `changed` trigger; measured, the benign band is 0.19–0.22 and `layer1_hash` alone is 0.1372, so that change recovers at most 0.09 of risk and an 8-article lazy append still reads `changed` on `layer2 = 0.1231 > NOISE_FLOOR`. **Remedy design must change** (see O-SA-9).
5. **`AUDIT-4-6`'s "layer 3 doesn't score reference deletion" is incomplete.** All five reference kinds score exactly 0.0, not just scripts/iframes — including the site's own `<form action>` and `<link href>`. And layer 2 has a parallel, previously-unrecorded blind spot: **un-hiding** a hidden farm scores 0.0 with zero structural churn.
6. **`AUDIT-2-3`'s "staged/time-delayed payloads: genuinely absent" is half-wrong.** The client-side delayed-render slice **is** caught when the payload is DOM text (risk 1.0, `flagged`); only the timed-`<script>`-string form evades (0.3153). Corollary the remedy must cover: AUDIT-2-3's "parse meta-refresh in layer 3/7" specification would miss the script-string form entirely.
7. **`AUDIT-4C-2`'s "`wk_` key prefix in the public schema" is not reproducible.** 0 hits across the 99,585-byte OpenAPI document. The finding stands on 8 other items.
8. **Three comments assert constants that have moved** (extending AUDIT-4F-5's class into the detection tree, where it was logged as out-of-scope): `worker/detection/fusion.py:40` and `:192` assert **0.35** against a real 0.40; `worker/scan_tasks.py:48`'s "(~0.03)" benign-risk figure is **~7x too low** (measured band 0.19–0.22); and `worker/detection/metadata.py`'s and `signatures.py`'s docstring claims ("security-header downgrades score", "lexicons run on NEW text only") are **substantively false** (6 of 8 CSP relaxations score 0.0; 7 of 9 adversarial shapes make 100 % of the page "new"). **One claim verified exact**: `scan_tasks.py:58`'s "min observed: 0.0518" reproduces from the committed artifact (`combined_subthreshold-0015`).
9. **Two of Phase 4's handoff specifications are off target** (AUDIT-4-7 §1 — layer 4 already top-crops for SSIM; AUDIT-4-8 §2 — hidden-state resolution is already symmetric per side). Conclusions unchanged, designs need narrowing.
10. **The effort's "suites are green, therefore CI is green" implication is now known to be structurally unverifiable.** AUDIT-4E-11 is worse than logged: `ruff check .` fails on the *first* command of the backend job, so nothing behind it runs. Every "the suite is green" statement in this log is an observation about a local run, which is exactly what it claims to be — but nothing in the repository enforces it.
11. **No encoding defect**: the `§` characters in `worker/detection/*.py` and `worker/llm_escalation.py` are intact U+00A7; a byte-level sweep of every `backend/**/*.py` for U+0013–U+0017 found zero stray control characters.

#### Findings out of scope (routed, not investigated)

- **AUDIT-SA5-4's 7 `ruff` errors in `backend/tools/run_stress_catalog.py`** belong to the Phase 5A stress harness — Phase 5A needs them clean before its gate can go green. Logged here because they are the *first* command of the backend CI job.
- **`AUDIT-SA5-7`'s `LOGIN_RATE_LIMIT_PER_IP`** and **`AUDIT-SA3-7`'s missing `depends_on: db`** both belong to Audit Phase 9's ops/infra pass (`OPS-1`…`OPS-8`), which is the phase that owns `.env.example`↔compose↔scripts drift.
- **AUDIT-SA2-2's CSP direction classifier remedy** needs a token-semantics table (which CSP source expressions are more restrictive than which) — a CSP-spec design question for the remediation prompt's own design phase, though the code fix is confined to `worker/detection/metadata.py`.
- **AUDIT-SA2-3's cloaking re-tune requires a new corpus axis first** (`partial_cloaking_small_payload` across >= 3 reference sizes) — that axis's design belongs to Phase 8's fixture work; the gap list is supplied above.
- **Layer 4's interaction with *interactive* pages** (ads, consent widgets, carousels, sticky headers) — the render-noise measurement used a static page, and these are exactly the elements AUDIT-3-1/3-2 showed can render nondeterministically. Routed to Phase 8's adversarial fixtures.
- **`AUDIT-4F-6`'s bidi gap is latent today** but Tier C (`aljazeera.net`, `bbc.com/arabic`, `haaretz.co.il`) exists precisely to exercise it — fixing before Phase 5C is cheaper than re-auditing rendered screenshots afterwards.
- **Ops agent + Telegram surfaces** remain excluded per §0; neither subagent audited them, and the only note is Phase 2B's existing boundary determination (re-confirmed by the AI/infra subagent: `app/agent/` reads through the same service layer and does not bypass RBAC).

#### Coordinator notes for Session B

- **XS-9 is a sequencing constraint, not just a finding.** AUDIT-SA1-2 predicts that Phase 5A+5B's Tier-B sites (Akamai, DataDome, PerimeterX, AWS WAF, Turnstile) will fail *because the wall detector is Cloudflare-only*, not because of per-site flakiness. Session B should either fix the wall classifier first or record the prediction as the expected baseline for those categories so Rule 19 per-case root-causing is not mis-directed.
- **Deployment parity is now clean (57/57 file comparisons across three subagents)**, so Session B's live probes are all HEAD-valid. AUDIT-4B-8's "rebuild before remediation verification" prerequisite is satisfied.
- **The `ruff check` failure at HEAD is now the first CI gate** and will block any remediation PR. It should be sequenced first in whatever remediation prompt follows.
- **The three new Session A test files are the only repo changes from this session** and are the durable characterization baseline for a remediation prompt: 138 tests that assert current behaviour and will need their specific assertions flipped as each finding is fixed.

- **Commit**: *pending — the user has not requested a commit for this session; the working tree holds this log entry, five scratch reports, and three new characterization test files, with zero production modifications.*
- **Next**: Session B — `SESSION-B-KICKOFF.md`, Wave 1 (Phases 5A+5B, 8, 9 in parallel).

---


---

### [DONE] PROMPT-003 Audit Phases 5A+5B+5C — Stress-Test Catalog: All Tiers (Subagent W1-A)

- **Prompt**: SESSION-B-KICKOFF.md (subagent W1-A, Wave 1)
- **Session date**: 2026-09-30
- **Assigned subsystem**: the capture pipeline under real-world site load, across every tier of `PROMPT-003-stress-site-catalog.md`
- **Full report**: `scratch/session-b-stress-testing.md` (2,559 lines, 83 per-site `### FAIL` blocks). Everything below is a coordinator integration; the scratch report is the evidence of record.

- **Environment attestation**: measured against the live Docker install (worker performing real Playwright captures). Host AMD Ryzen 5 5625U 6C/12T, Docker ceiling 7.429 GiB. **All latency figures were taken under CPU/RAM contention with two sibling Wave-1 subagents** and are relative comparisons, not clean absolute measurements (W2's numbers, taken alone, are the clean ones).

- **Method**: production `worker.fetcher.fetch_page` in child-process isolation via `backend/tools/run_stress_catalog.py` and its helper `backend/tests/_capture_child_impl.py`, with a **180 s per-capture budget**. Each capture additionally recorded `http_status`, the production `looks_like_challenge_page` verdict, independent vendor fingerprinting (headers, cookies, challenge-DOM markers), and the fused detection risk/verdict obtained by running the deployed `run_detection` on the capture pair.

- **Execution plan & two stated deviations**: (1) the catalog yields **88 Tier-A entries but only 69 unique URLs** (19 sites appear in two category blocks); W1-A executed the 69 unique URLs and mapped each result back to *every* category that URL belongs to, preserving per-category attribution while saving ~27% of capture time. (2) Execution was ordered B→C→A so the two tiers that yield new findings completed first. Both deviations are stated and justified in the report.

- **Coverage — COMPLETE**: **121/121 unique URLs × 3 passes = 363 captures** (Tier A 69, B 31, C 21). Rule 18 satisfied at 3 passes/site.

- **Stress-test results** (dense summary; **every failing site has an individual `### FAIL` block with root cause + Fix-candidate/Accepted-risk in the 27-row disposition ledger**):

  | Tier | Captures OK | Sites 3/3 | Detection pairs | `clean` / `changed` / **`flagged`** | Walls stored as content |
  |---|---|---|---|---|---|
  | A | 180/207 | 56 | 177 | 33 / 89 / **55 (31%)** | **7** |
  | B | 80/93 | 25 | 77 | 3 / 29 / **45 (58%)** | **8** |
  | C | 52/63 | 15 | 49 | 4 / 24 / **21 (43%)** | **4** |

  Per-site pass/variance rows for all 121 sites are in the scratch report. Passing sites take one line each there, as §6.1 requires; no aggregate-only rows were accepted anywhere.

- **Session A's XS-9 prediction — VERIFIED, with a correction that matters.** `AUDIT-SA1-2` (Cloudflare-only wall detector, no `http_status` gate on the scan path) held exactly as predicted. **The correction:** Tier B's failure is **bifurcated**. 29 of 31 Tier-B sites captured *cleanly*; the dominant damage is not wall storage but **false-flagging commercial pages** — 58% of real consecutive-visit pairs `flagged` at a median fused risk of **0.79 with no attack present**. This is a third, separable defect (register H9) and is why the Tier-B results must not be read as "bot walls block capture".

- **Findings (20)**: 2 Critical, 6 High, 8 Medium, 4 Low.
  - **Critical** — `AUDIT-5C-1` (a 200-OK onboarding dialog / login wall is stored as a healthy, ready, current baseline by the deployed stack; the next scan of the real page flags at risk **0.99999**) → register **C11**; `AUDIT-5C-6` (a **controlling** Service Worker registers under the production capture context on `web.whatsapp.com`, live-confirming Session A's `AUDIT-SA1-1`) → merged into register **C1**.
  - **High** — `5A-1` ad/prebid host rotation scored as injection, predicted `1-exp(-0.9)=0.5934` and measured **exactly 0.5934** → merged into **H8**; `5A-2` capture-completeness variance flags at 0.998; `5A-3` a 0.65% rendered-height delta flags BBC News at 0.7633; `5A-7` seven ordinary Tier-A homepages are walled and **`reuters.com` serves its wall on HTTP 200**; `5B-1` six non-Cloudflare walls stored as `capture_quality: "full"`, one a **401 Anubis PoW gate** the catalog does not list; `5B-2` 58% of Tier-B pairs false-flagged → `5A-2`/`5A-3` merged into **H7**, `5A-7`/`5A-4` merged into **H9**.
  - **Medium** (8) — `5A-5` DNS failure surfaced as `SSRFBlockedError` which the retry contract permanently excludes from retrying → merged with W2's `7-4`; `5A-6` the mandated stress runner **cannot detect the failure mode Tier B exists to catch** (a bot-wall capture is recorded as a clean PASS); `5B-4` `ERR_HTTP2_PROTOCOL_ERROR` classified transient and still failing 3/3; `5B-5` catalog drift, measured and timestamped; `5C-2` the height-only screenshot guard fails on 7 of 52 Tier-B/C sites (widths of 4,000 px and 1,378 px captured **uncapped** with `capture_quality: "full"`); `5C-3` inner-container scroll captured as a single viewport; `5C-4` `apnews.com` reproduces the scroll-shrink path live (`initial_height 15368 → final_height 768`, still `full`); `5C-5` `india.gov.in` returns 403 to the browser but 200/607 KB to Wardress's own probe.
  - **Low** (4) — `5A-8` `archive.org`'s `noscript` fallback stored as a complete capture; `5A-9` runner budget exhaustion on one site and one site lost to the DNS outage (**Accepted-risk**, environment).

- **Log-vs-reality**: W1-A made **five documented self-corrections to its own wall detector**, each driven by a counter-example in its own data, and stated them in the report. It also falsified **three "extremely large page" premises** and **two lazy-load/DataDome category claims**, now recorded in the catalog file itself (the catalog's "How to extend" section requires drift to be recorded there, not only in the log).

- **Opportunities / Innovation ideas** (Rule 17): the 27-row disposition ledger's non-Fix-candidate rows, plus the observation that **a `ready` baseline should carry a provenance label** ("captured from a page that answered 200 but is implausibly small relative to its own screenshot") so an operator can see poisoning directly.

- **New hermetic tests added**: none committed. No test file was added by this phase; its value is its measurement set, preserved in the scratch report per Rule 10.
- **Regression**: no repo file changed by W1-A, so no suite was owed per Rule 5.

---

### [DONE] PROMPT-003 Audit Phases 6+7 — Concurrency, Scale & Chaos Testing (Subagent W2)

- **Prompt**: SESSION-B-KICKOFF.md (subagent W2, Wave 2 — run alone)
- **Session date**: 2026-09-30
- **Assigned subsystem**: Celery worker/beat orchestration under concurrency, scale and fault injection
- **Full report**: `scratch/session-b-concurrency-chaos.md` (769 lines). Coordinator integration below.

- **Environment attestation**: **W2 ran with the machine to itself — no sibling contention** — which is the reason it was sequenced after Wave 1, and the reason its timings are the clean ones in this audit. Isolated audit stack (same images) on scratch DB `wardress_audit` and Redis DB 9; the live worker/beat were stopped during load testing and restarted after.

- **Configured limit = 12 (prefork), proven four ways**: no `-c` in `Dockerfile.worker:36`; no `command:` override in `docker-compose.yml:89-116`; no `worker_concurrency` in `celery_app.py:23-46`; and 12 live children matching Celery's own `concurrency: 12 (prefork)` banner. **1× = 12, 2× = 24, 5× = 60.**

- **Load-test results** (3 passes each, cheap page profile):

  | Level | E2E p50 | Queue p50 / p95 | Throughput | Failures | Peak worker memory |
  |---|---|---|---|---|---|
  | 1× | 25.2–37.7 s | 0.2–0.4 / 0.3–0.5 s | 0.290–0.456/s | 0/36 | — |
  | 2× | 31.6–34.5 s | 10.4–10.7 / 20.7–24.6 s | 0.491–0.516/s | 1/72 | — |
  | 5× | 64.9–**309.5 s** | 47.1–**282.5** / 95.9–323.9 s | 0.156–0.462/s (**2.96× spread**) | **0 → 8 → 17 of 60** | **6.52–6.67 GiB = 85.8–87.8% of ceiling** |

- **Where it breaks, and why (heavy profile)**: per-scan cost rose **34.6 s → 318.7 s (9.2×) at 1×**, of which **83–94% is outside the capture** — 12 prefork children × 6 torch threads on 6 cores, with `torch.get_num_threads() = 6` and nothing pinning it. The next 12-scan batch **all hit the 420 s soft / 480 s hard time limits → SIGKILL → 12 scan rows stuck `running` with `error = NULL` for 25+ minutes.**

- **Amplification cascade (`AUDIT-4B-2`) — CONFIRMED and worse than predicted.** Session A had deliberately not run this live. Measured: supersession fires at K=5, 15, 30 and 60 alike — **the trigger is age, not backlog depth**; 192 superseded rows with 40 new pending rows enqueued in a single tick. Session A predicted "amplification begins at a backlog of ~15–60 pending rows"; measured, **any** backlog older than 10 minutes triggers it.

- **Soak run (50 sequential cycles, no worker restart)**: **50/50 completed, zero failures, zero state leakage.** Memory 4,933 → 5,080 MB = **step-then-plateau**, flattening from cycle ~36 — which *contradicts* a naive unbounded reading of `AUDIT-4B-7`. But a **different** resource grows without bound: **zombie processes +2.0 per cycle, perfectly linear, 1,444 → 1,546**, with no plateau. The recycle policy chosen was "no recycle", justified by Session A's proof that `--max-tasks-per-child` does not help because model memory is never released.

- **Chaos & failure-injection results** (7 spec scenarios + 4 additional; each classified safe fail / silent success / worker crash):

  | # | Scenario | Passes | Classification | Headline |
  |---|---|---|---|---|
  | 1 | Crash mid-capture (SIGKILL) | 3/3 | **worker crash** | Row orphaned; **the broker does NOT redeliver** (`task_reject_on_worker_lost` defaults False) |
  | 2 | Blackholed DNS | 3/3 | **silent misreport** | `getaddrinfo` blocks the event loop **8.004 s** and reports `SSRFBlockedError` |
  | 3 | Slow-loris | 3/3 | **unbounded** | 271.9 / 271.8 / 272.35 s — **13.6× its own 20 s budget**, 57% of the hard limit |
  | 4 | Malformed HTTP | 3/3 | 3 safe fail, **1 SILENT SUCCESS** | → register **C12** |
  | 5 | SSRF redirect / internal matrix | 3/3 | **safe fail — policy holds** | **27/27 blocked** |
  | 6 | Pathologically large DOM (>10 MB) | **1 pass only** | see coverage note | |
  | 7 | Streaming chunked body bomb | 3/3 | **unbounded** | +13.9 / +50.4 / +141.1 MB for 10 / 60 / 200 MB, linear |
  | +1 | Kernel OOM of `chrome-headless` | 3/3 | **worker crash** | 12 children = 5.6 GiB = 75.4% at the OOM instant |
  | +2 | Docker management API unavailable | 3/3 | **operator-invisible outage** | 500s for ~9 minutes |
  | +3–5 | Postgres restart / Redis loss / network partition | **0 passes** | **NOT TESTED** | budget exhausted — flagged, not hidden |

- **Findings (11)**: 2 Critical, 4 High, 4 Medium, 1 Low.
  - **Critical** — `AUDIT-7-1` (a truncated/malformed **200** response is silently promoted to a trust anchor as a 39-byte empty page, and the site then reads **`clean` forever** at risk 0.0063) → register **C12**; `AUDIT-6-1` (at its own configured concurrency the worker exhausts the Docker memory ceiling: the kernel OOM-kills Chromium, killing other concurrent work, Celery SIGKILLs children on the hard limit, and the Docker API becomes unusable for ~9 min) → register **C13**.
  - **High** — `6-2` the worker leaks **exactly 2.0 zombie processes per scan cycle, linearly and without bound**; `7-2` the metadata probe has **no total deadline** (271.9 s = 13.6× its budget); `7-3` `probe.py` buffers the entire hostile response before slicing, scaling linearly and unbounded with attacker-chosen body size (this is `NB-CAP-1`, first proven); `6-3` scan cost inflates 9–16× at full concurrency while throughput improves only 1.3–1.6×.
  - **Medium** — `7-4` a DNS failure is reported as an SSRF policy refusal **and** the synchronous SSRF gate freezes the API event loop for the full resolver timeout (merged with W1-A's `5A-5`); `7-5` a worker SIGKILL leaves the scan row `running` forever with no broker redelivery; `6-4` at 5× the failure rate is highly non-deterministic (**0/60 → 8/60 → 17/60 across three identical passes**); `6-5` overload amplification confirmed (merged into `AUDIT-4B-2`).
  - **Low** — `6-6` Chrome Desktop UA / model-catalog task-naming drift.

- **Log-vs-reality**: Session A's 79% warm-pool extrapolation **verified** (75.4% at the OOM instant, 85.8–87.8% running) and its 624.5 MB/child re-measured at **582.6 MB**. W1-A's bogus `SSRFBlockedError` observations were **reproduced and root-caused** to `ssrf.py:55-58`. `AUDIT-4B-2`'s entry threshold was **revised downward** (see above). `AUDIT-4B-7`'s "unbounded growth" reading was **partially refuted** — worker memory plateaus; the unbounded resource is a different one.

- **Opportunities / Innovation ideas** (Rule 17): bound `torch.get_num_threads(1)` per child and cap prefork concurrency against the **Docker** ceiling rather than the host's RAM; reap child processes; a wall-clock deadline across the whole metadata probe rather than per operation; stream the probe with an incremental byte cap.

- **Full regression results**: **1471 passed, 1 failed, 20 xfailed.** The single failure is `test_confirm_cancel_race_single_winner` — an **agent-subsystem** test outside W2's assigned scope, which **passes in isolation**; it is not a regression from this session.

- **Final state attestation**: all five services back up and healthy, API `200`, live database clean (`sites=0 scans=0 baselines=0 alerts=0`), scratch database dropped, audit containers and volumes removed, `git status --short` identical to session start.

---

### [DONE] PROMPT-003 Audit Phase 8 — Adversarial Detection Accuracy Stress Test (Subagent W1-B)

- **Prompt**: SESSION-B-KICKOFF.md (subagent W1-B, Wave 1)
- **Session date**: 2026-09-30
- **Assigned subsystem**: all nine detection layers + fusion, as deployed
- **Full report**: `scratch/session-b-detection-accuracy.md` (624 lines). Coordinator integration below.

- **Method**: **85 hermetic attack/benign fixture pairs** (57 attack, 21 benign, 7 control) pushed through the deployed `run_detection`, with **real Chromium 149 screenshots on both sides** — including a genuine server-side asset-swap mechanism (same URL, different bytes) and a real 12-pair glyph-outline-swapped TTF for the font-hijack fixture. **273 pipeline invocations, every fused-risk pstdev exactly 0.000000.** Rule 18 is trivially satisfied because the pipeline is a pure function of `PageData`.

- **Stress-test results**:

  | Class | Count | Result |
  |---|---|---|
  | Attack — **below the 0.40 material bar** | 57 | **22 (38.6%)**, of which **3 read `clean`** |
  | Benign — **cross 0.40** | 21 | **13 (61.9%)**; **12 (57.1%) alert**; 1 burns an LLM call per scan |

  Every miss and every false positive has an individual root-cause block (Report §4) and an explicit Fix-candidate disposition (Report §3). No aggregate-only rows.

- **The mandated visual-only fixtures (`NB-DET-1`) — all three CAUGHT**: `<style>` invert **0.9999** · `@font-face` glyph hijack **0.9979** · canvas **0.9998/1.0000** · SVG-geometry **0.9998**. The brief's crux resolved cleanly: **layer 4 returned a measured value on 85/85 fixtures, never degraded, crashed 0 times** — the capture→screenshot path is not the limiting factor anywhere.

- **But the benign twins are the actual finding, and they are louder than the attacks they were paired against**: a **legitimate webfont swap flags at 0.9995** (L4 0.3627) versus the glyph hijack's 0.3043; a **responsive breakpoint change with byte-identical HTML flags at 1.0000** (L4 0.6293). Layer 4 has no notion of *why* pixels differ → register **H7**, a new class present in no prior phase. The remedy shape is O-8-1, a `capture_context` channel fusion treats as *explanation* rather than evidence.

- **Findings (15)**: **4 Critical, 9 High, 2 Medium** *(W1-B's own summary line said 5/8/2; its per-finding detail tables — which the coordinator treats as authoritative — read 4/9/2.)*
  - **Critical** — `8-1` CSP widening is a **false `clean`** (layer 6 exactly 0.0000, fused 0.0019 with real screenshots on both sides) and a `<meta http-equiv>` CSP is never read at all → merged into **C5**; `8-3` layer 4 has **no area floor**, with a hard cliff at ~0.1% / ~0.5% of compared area → register **C7**; `8-4` layer 7 is a **step function of page size** (0.1032–0.1296 on small pages, exactly 0.0 on realistic ones) → merged into **C6**; `8-5` revealing hidden content is invisible and removal-only defacement scores exactly 0.0 → register **C8**.
  - **High** — `8-2` HSTS neutralisation scores 0.1 → C5; `8-6` the `_new_text` collapse also false-flags **punctuated** pages, so the "unpunctuated only" mitigation does not hold → merged into **C4**; `8-7` removal-only defacement → C8; `8-8` `<base href>` and event-handler payloads invisible to layer 3 → register **H18** (new); `8-10` the `bbox` suppression primitive is total (conclusive defacement → 0.1372 `changed`) → merged into **H6**; `8-12` breakpoint change flags at 1.0 → merged into **H7**; `8-13` legitimate content/layout changes flag → register **H19** (new); `8-14` layer 4 cannot distinguish a glyph hijack from a legitimate webfont swap → **H7**; `8-15` every widget/vendor-script/new-stylesheet shape flags → merged into **H8**.
  - **Medium** — `8-9` a `<noscript>` defacement is invisible to Wardress's own screenshot and a `title=` tooltip payload to every channel; `8-11` a timing-out suppression rule manufactures the delta it was meant to silence → merged into **H6**.

- **Log-vs-reality — the single most important methodological note in this audit.** W1-B **refuted four Session A / Phase 2 numbers in the direction that looks alarming but is not**: single-word tampering 0.1942 → **0.6718 `flagged`**; `<meta http-equiv=refresh>` 0.1987 and `location.replace` 0.3153 → **1.0000 `flagged`**; same-origin phishing overlay 0.2242 → **0.9993 `flagged`**; over-broad suppression 0.195 → **0.7044 `flagged`**. **The cause is method, not product**: Session A's synthetic fixtures carried **no screenshots**, so layer 4 was `degraded` and contributed nothing; W1-B used **real Chromium renders**, and production always has screenshots. Where the two diverge, **W1-B's numbers are the more faithful measurement of deployed behaviour.** Consequently `AUDIT-2-2`'s "subtle single-word tampering is genuinely absent" and "only a new-domain overlay is caught" are **invalidated**.

  Conversely, Session A's headline numbers were **confirmed digit-for-digit** where method did not differ: 36 of 323 benign rows reaching 0.40 and **34 exceeding the 0.50 flag threshold**; `vendor_script_added` mean 0.7538 / max 0.8269; `site_redesign` max 0.8454; `sanity_benign_quiet` 0.6583; the corpus guard at 0 of 56; and the `(a|aa)+b` ReDoS timeout — which W1-B **sharpened** into a stronger result: the optimizer is **position-sensitive, not pattern-insensitive** (the same pattern costs 2,001 ms as the first element and 1.0–2.0 ms as the last).

  W1-B also **corrected one of its own measurements** — an apparent "14.6 s ReDoS" that was its own host-contention artifact, not a pattern — and recorded it explicitly so the number is not rediscovered as new.

- **Two questions Session A routed forward, answered**: layer 4 on **interactive** pages is **sound** (4 render pairs, L4 0.0031–0.0149, `clean` 4/4, **16× below** the 0.2225 escalation bar); and the hue-only brand-refresh worry is **resolved in the system's favour** (real `hsl()` render 0.1921, **18× below** the material bar).

- **Verified-clean ledger** (measured, not doc-trusted): the layer-1 hash gate resisted **10/10** whitespace and normalisation bypass shapes; the identical-hash gate was never the source of any miss; churn padding does not dilute an attack (defacement + 40 articles = 1.0000); pipeline determinism exact; no fixture produced a degraded layer except one that intentionally degraded the UA probe.

- **New hermetic tests added**: `backend/tests/test_phase8_adversarial_detection.py` — **12 passed, 20 xfailed**, `ruff check` and `ruff format --check` clean. The 20 `xfail` entries are **characterization guards** a remediation prompt flips as it fixes each finding (Rule 5: a red suite is never an acceptable end state).

- **Full regression results**: detection 12-file batch **222 passed** (exact baseline); 10-file batch + Session A file + new file **331 passed, 20 xfailed**; new file alone 12 passed / 20 xfailed.
- **Coverage — stated honestly (Rule 8)**: interactive-page layer-4 work used a synthetic interactive fixture, not live sites; the corpus axis additions recommended by the report are designs, not implementations (Rule 1).

---

### [DONE] PROMPT-003 Audit Phase 9 — Performance Profiling, Infrastructure & Operational Consistency Audit (Subagent W1-C)

- **Prompt**: SESSION-B-KICKOFF.md (subagent W1-C, Wave 1)
- **Session date**: 2026-09-30
- **Assigned subsystem**: capture + detection performance, the PowerShell operational lifecycle (`OPS-1`…`OPS-8`), Docker topology, documentation drift (`DOC-1`…`DOC-8`), and dead code
- **Full report**: `scratch/session-b-performance-ops.md` (1,057 lines). Coordinator integration below.

- **⚠️ Explicit note on the Rule 15 conflict, and how it was resolved.** The Session-B brief asked W1-C to run a full `uninstall.ps1` backup → fresh install → `RESTORE.txt` replay "if possible". **It was not possible without violating Rule 15** — an absolute, non-negotiable rule of the audit spec — and without destroying the live volumes two sibling subagents were actively testing against. **W1-C did not run `install.ps1` or `uninstall.ps1`.** It substituted: (a) static analysis of the backup and restore code paths with a **bidirectional artifact-coverage cross-check** (every artifact the backup creates is referenced by the restore, and vice versa), labelled **medium-high confidence with the end-to-end replay UNVERIFIED**; and (b) for `diagnostics.ps1`, it copied the two scrubbing functions **verbatim** into a scratch harness pointed at a **synthetic** `.env` — the real one was never read. `update.ps1` and `install.ps1` were audited by **reading**, never by running; `update.ps1`'s merge logic was exercised only as copied code against synthetic fixture pairs.

- **Method**: `cProfile`, `docker stats`, `EXPLAIN` against the live DB (read-only), and manual A/B interleaving with stated n. **All timing figures were taken under contention** with two sibling subagents on a 6-core host and are labelled as such; the A/B *comparisons* are decision-grade, the absolute numbers are not.

- **Profiling results** (decision-grade A/B comparisons):

  | Candidate | Measured | Verdict |
  |---|---|---|
  | Batched MiniLM | 24 calls 606.8 ms → 1 batched 345.0 ms = **1.76× / −261.7 ms per scan** (n=3) | **VALID — highest-value optimisation** |
  | Per-task DB engine | 95.06 ms fresh vs 5.32 ms pooled = **17.9× / 89.74 ms wasted per task** (n=5) | **VALID** (needs `pool_size=1`) |
  | Layer 8 cost | **93–95%** of a 14 KB page, but **saturates at 2.4–3.0 s**; L2 grows 1.12 → **138.90 ms** from 0.3 KB → 171 KB, **unbounded** | L8 is bounded by design; **L2/L3/L5 are the scaling risk** |
  | "Resize once per layer-4 call" (O-SA-3) | **+34.3 ms @1280×3000, −21.9 ms @1280×4000** — the sign flips | **INVALIDATED — do not implement** |
  | Fusion reload | **0** `json.loads` in 6,000 calls; 0.0135 ms/call | **INVALIDATED** |
  | Regex recompilation | 17 module-level `re.compile`; hot inline site **1.725 µs** | **INVALIDATED** |

- **Soft-block baseline poisoning (`NB-CAP-2`) — PROVEN END TO END.** Through the real `capture_baseline`/`run_scan` bodies on a scratch database: a 200-OK Cloudflare wall → baseline **`ready`, `is_current=True`**; the next scan of the **real** page, 22.34 s later → **`flagged`, risk 0.9999999999997338**, cadence tightened to 15 min. Control (healthy anchor, same page, one tick later): **0.3, `changed`, 22 min**. Positive control confirms the `>= 400` guard works when it fires. → register **C11** (independently reproduced by W1-A through the live worker).

- **Findings (17)**: **0 Critical, 5 High, 9 Medium, 3 Low.** W1-C states explicitly that it found no false-clean and no exploitable boundary the earlier phases had not already rated Critical, and that it **declined to escalate `AUDIT-9-1` above High** because it is a false *alarm*, not a false *clean* — which is correct per §6.4 and is overridden to Critical only because W2's `AUDIT-7-1` proved the same missing gate *does* also produce a false `clean` (register C12).
  - **High** — `9-1` soft-block baseline poisoning → **C11**; `9-2`/`OPS-1` `update.ps1` performs **no `.env` reconciliation at all** and the live `.env` is already **14 documented keys behind** → **H20**; `9-3`/`OPS-2` `validate.ps1`'s `< 4 GB` check **does not fire at all** on this host → **H21**; `9-4`/`OPS-4` `diagnostics.ps1` **does not scrub the product's own `wk_` keys** — 9 of 16 hostile shapes escape → **H22**; `9-5`/`OPS-5` the restore path silently downgrades the schema and reports success on a partial load → **H23**.
  - **Medium** (9) — `9-6` every `<link href>` scores 0.6 regardless of `rel`; `9-7` three comments assert a 0.35 material bar (real 0.40) and the benign-risk comment is **10× off**; `9-8` the ReDoS guarantee covers user suppression rules but **not the normaliser that runs on every scan**; `9-9` the entire backend CI gate is dead behind a 9-error `ruff check .` → merged into H3's group (`AUDIT-4E-11`); `9-11` `beat` still declares no `depends_on: db` and 3 of 7 services have no healthcheck → merged into `AUDIT-SA3-7`; `9-12` `TRUST_PROXY_HEADERS` is documented without the one condition that makes it safe → merged into `AUDIT-SA4-2`; `9-13` `/api/health` is an orphaned public route disclosing database liveness → merged into `AUDIT-SA4-9`/`4C-5`; `9-14` `celery_app.py`'s "acknowledge late" claim is false; `9-15` `/openapi.json` is public, unmetered and narrates the SSRF gate → merged into `AUDIT-4C-2`.
  - **Low** (3) — `9-10` three dead entry points the code-walking method cannot reach; `9-16` `lib.ps1` has a Windows argument-quoting bug no current caller can reach; `9-17` the beat schedule file lives in the container's writable layer and is undocumented → merged into `AUDIT-4B-8`'s residual.

- **Two briefing premises were falsified, and W1-C said so rather than accommodating them** — the correct behaviour under Rule 13. (a) *"Verify `update.ps1`'s `.env.example` vs `.env` merge behavior"* → **no merge exists**; the premise being wrong *strengthens* the finding. (b) *"Verify `diagnostics.ps1` scrubs `wk_` API keys"* → **the claim is false**. A third, `DOC-3`'s Telegram-bot DB-bypass diagram, **is not present in the repository at all** and is restated as such.

- **Verified-clean results** (recorded, not dressed as findings): `docs/docs.json` navigation resolves **24/24 with zero orphans in both directions**; `ruff check .` reproduced at **exactly 9 errors**, same file, same rule; `/docs/oauth2-redirect` at **exactly 3,012 B**; the OpenAPI schema reconciled to **92,500 B live** with Session A's 99,585 B **marked superseded** (it could not be reproduced under any encoding and its provenance was not guessed).

- **Coverage gaps stated honestly (Rule 8)**: the **DB-index `EXPLAIN` sweep is unverified at production scale** — its seed failed on a schema mismatch (`sites.updated_at` does not exist), so both passes are empty-table plans; N+1 absence was verified by source reading instead, and Session A's dispatcher-query numbers stand unchallenged. W1-C did not re-measure Session A's capture-side or frontend performance work (contention territory). It also caught itself nearly publishing a wrong number: an early fixture lacked screenshots, which tripped `_UNMEASURED_RISK_CEIL = 0.30` and pinned every variant at exactly 0.30; re-measured with real PNGs, the honest benign band across both sessions is **0.19–0.30**.

- **New hermetic tests added**: **none committed**; zero test files added, by deliberate choice (Rule 5/10) with the reasoning recorded.
- **Environment hygiene**: scratch database `wardress_w1c_test` created and **dropped**; live database verified clean; one artifact-root escape to `C:\data\artifacts` found, cleaned, and its redirect fixed; the Docker stack left running and healthy for its siblings.

### [DONE] PROMPT-003 Audit Phase 10 — Consolidated Findings Register & Opportunities Register (Audit Completion)

- **Prompt**: SESSION-B-KICKOFF.md (coordinator model — Phase 10 executed directly per §4 Wave 3)
- **Session date**: 2026-09-30
- **Assigned subsystem**: the entire audit. This phase reads every prior entry (Phases 1–4F), Session A's deep verification, and all four Session B scratch reports, and consolidates them into one deduplicated register.
- **Do not touch code.** No production file was modified anywhere in this phase or this session.

#### Environment attestation (Rule 13)

Docker stack up and healthy at phase close: `wardress-app-1` (:8321, healthy), `wardress-worker-1`, `wardress-beat-1`, `wardress-db-1` (healthy), `wardress-redis-1` (healthy). `GET /api/health` → `200 {"status":"ok","service":"wardress-api"}`. Host: AMD Ryzen 5 5625U, 6C/12T, 15.34 GB RAM; Docker ceiling 7.429 GiB. Playwright 149.0.7827.55; `run_detection` 54.71 s cold / 0.03 s warm. Live database verified clean at close (`sites=0 scans=0 baselines=0 alerts=0`). W2's scratch database and audit containers/volumes were dropped; the pre-existing `wardress-test-pg` container from Session A remains and is the documented harness, not Session B residue.

#### Rule 1 / Rule 5 attestation for the whole of Session B

`git status --short` shows **zero modifications to any tracked production file** across all four subagents. The only new files are the four scratch reports and one new test file. No subagent ran a git state-changing command; none committed. No `install.ps1`/`uninstall.ps1` was ever executed (Rule 15). No throwaway data was left in the live database.

#### Sources consolidated

| Source | Scope | Raw finding entries |
|---|---|---|
| `PROMPT-003-IMPLEMENTATION-LOG.md` Phases 1–4F | 10 completed audit phases | **73** |
| Session A (5 parallel subagents) | independent deep verification of Phases 1–4F | **45** |
| `scratch/session-b-stress-testing.md` (W1-A) | Phases 5A+5B+5C | **20** |
| `scratch/session-b-detection-accuracy.md` (W1-B) | Phase 8 | **15** |
| `scratch/session-b-performance-ops.md` (W1-C) | Phase 9 | **17** |
| `scratch/session-b-concurrency-chaos.md` (W2) | Phases 6+7 | **11** |
| **Total raw entries** | | **181** |
| **After deduplication (below)** | | **163 canonical** |

---

## 1. SEVERITY SUMMARY

| Severity | Raw entries | **Canonical (deduplicated)** | Notes |
|---|---|---|---|
| **Critical** | 18 | **13** | 5 raw entries collapsed into canonical Criticals |
| **High** | 41 | **27** | 14 raw entries collapsed |
| **Medium** | 82 | **79** | 3 collapsed |
| **Low** | 40 | **44** | 4 Low findings were *escalated* by later phases, so the canonical Low count exceeds its raw count |
| **Total** | **181** | **163** | 18 duplicates merged; 6 severity escalations applied |

**Every entry carries a disposition.** Of the 181 raw entries, 175 are **Fix-candidate** and 6 are **Accepted-risk** (each individually justified in its own entry and surfaced for the user's accept/reject decision below). **No finding is left pending.** W2's three untested chaos experiments are the only open items, and they are coverage gaps with an explicit recommendation, not undisposed findings.

---

## 2. MASTER FINDINGS REGISTER

Deduplicated across all phases and sessions. Sorted by severity, then subsystem. **Bold canonical ID** = the surviving entry; duplicate IDs in parentheses = merged evidence from later phases. Every ID is an anchor link back into this log or into the named scratch report.

### 2.1 CRITICAL (13)

| # | ID | Title | Subsystem | Source | Proposed remedy category |
|---|---|---|---|---|---|
| C1 | **[AUDIT-SA1-1](#audit-sa1-1)** (AUDIT-5C-6) | The Playwright SSRF route guard is `page.route`-scoped: Service Workers and `window.open()` popups bypass SSRF validation completely, with full read-back into a stored artifact | `worker/fetcher.py:287-340,543,518-525` | P4 (Session A) · P5C (W1-A) | `service_workers="block"` on `browser.new_context(...)` + `context.route("**/*", guard)`; correct three docstrings |
| C2 | **[AUDIT-4E-1](#audit-4e-1)** | The SSRF policy is skipped by three AI-provider reader paths and never re-checked on execution; the type-keyed private-network allowance reaches cloud metadata | `app/llm.py`, `app/ai_ollama.py`, `ai_config` | P4E (Session A) | Validate at the single point a `base_url` becomes a litellm deployment; review the type-keyed allowance itself |
| C3 | **[AUDIT-4E-2](#audit-4e-2)** (AUDIT-4E-2b) | The models.dev catalog fetch is outside the SSRF policy entirely, rides an unpinned client, and falsifies a documented "never raises" contract | `ai_catalog.py` | P4E (Session A) | Route through the shared outbound-fetch factory; validate the fetched schema before trusting it |
| C4 | **[AUDIT-4-1](#audit-4-1)** (AUDIT-8-6) | `_new_text` granularity collapses on unpunctuated pages — the "new-text-only" lexicons silently become whole-page lexicons; a benign edit reaches risk 1.0 `flagged` | `worker/detection/signatures.py` | P4 · P8 (W1-B) | Line-granularity fallback for pages with no sentence structure; cap `aggression_score`'s unbounded `Σw` as `topic_score` is capped |
| C5 | **[AUDIT-SA2-2](#audit-sa2-2)** (AUDIT-8-1, AUDIT-8-2) | A CSP widening is recorded as a **false `clean`** (risk 0.0019–0.0031); the direction classifier cannot resolve any real relaxation and calls an attacker-added origin "stronger". HSTS neutralisation scores 0.1. | `worker/detection/metadata.py:111-172` | P4 (Session A) · P8 (W1-B) | A CSP source-expression restrictiveness table; read `<meta http-equiv>` CSP |
| C6 | **[AUDIT-SA2-3](#audit-sa2-3)** (AUDIT-8-4) | Layer 7 is blind by scale: the additive ramp is anchored to `added/\|ref\|` so a conclusive cloaked banner scores **exactly 0.0** on any realistic page | `worker/detection/cloaking.py:86-118` | P4 (Session A) · P8 (W1-B) | Add an absolute-mass channel alongside the relative ramp; needs the `partial_cloaking_small_payload` corpus axis |
| C7 | **[AUDIT-8-3](#audit-8-3)** | Layer 4 has **no area floor**: a small defaced asset with an unchanged DOM is invisible, and there is a hard cliff at ~0.1% / ~0.5% of compared area | `worker/detection/visual.py:110-201` | **P8 (W1-B) — NEW** | Tile-localised layer 4; emit a `changed_area` evidence field |
| C8 | **[AUDIT-8-5](#audit-8-5)** (AUDIT-8-7, half of AUDIT-4-6) | **Revealing** hidden content is invisible (layer 2's sensitive channel is additive-only) and **removal-only** defacement scores exactly 0.0 on all five reference kinds | `worker/detection/dom.py`, `signatures.py` | **P8 (W1-B) — ESCALATED** · P4 | Bidirectional reference diff with element identity; a removal channel with its own weight |
| C9 | **[AUDIT-4E-4](#audit-4e-4)** | `weasyprint==69.0` ships an SSRF/arbitrary-file-read advisory, and the dependency gate the repo declares must fail on it is failing (12 advisories across 3 packages) | `backend/pyproject.toml`, `uv.lock` | P4E · P8 (Session A) | Dependency bump; triage `pyjwt`→2.14.0 and `oauthlib` (unreachable) |
| C10 | **[AUDIT-SA5-1](#audit-sa5-1)** | The locked `pyjwt==2.13.0` carries 10 advisories; one is **live-reachable as an unauthenticated HTTP 500** (a `RecursionError` escapes `except jwt.PyJWTError`) | `app/security.py::decode_access_token` | P4E (Session A) | Bump to ≥2.14.0 **and** harden the decode path against non-`PyJWTError` exceptions |
| C11 | **[AUDIT-5C-1](#audit-5c-1)** (AUDIT-9-1) | A **200-OK non-content page** (paywall, onboarding dialog, login wall) is promoted to a site's trust anchor; the next scan of the *real* page flags at risk **0.99999** | `worker/scan_tasks.py:109-118,262-272`, `worker/fetcher.py:166-201` | **P5C (W1-A) · P9 (W1-C) — TWO INDEPENDENT REPRODUCTIONS** | A content-shape gate at the baseline-promotion boundary (vendor-independent); see O-9A |
| C12 | **[AUDIT-7-1](#audit-7-1)** | A **truncated/malformed HTTP response with a 200 status** is silently promoted to a trust anchor (39-byte empty page), and the site then reads **`clean` forever** at risk 0.0063 | `worker/scan_tasks.py`, `worker/probe.py` | **P7 (W2) — NEW, OPPOSITE FAILURE DIRECTION to C11** | As C11, plus a minimum-plausible-content check on the stored artifact |
| C13 | **[AUDIT-6-1](#audit-6-1)** | At its **own configured concurrency** the worker exhausts the Docker memory ceiling: the kernel OOM-kills Chromium (killing other concurrent work), Celery's hard time limit SIGKILLs children, and the Docker management API becomes unusable for ~9 minutes | `worker` prefork, `Dockerfile.worker:36`, `docker-compose.yml:89-116` | **P6 (W2) — NEW** | Bound `torch.get_num_threads()` to 1 per child; cap prefork concurrency against the *Docker* ceiling, not the host's RAM; a `max_tasks_per_child` that actually works |

> **Coordinator note on C11/C12 — the most important synthesis in this register.** These two are the *same missing gate* producing **opposite** failure directions from the same code path. C11 poisons the anchor with junk and then alerts forever (a false **flag**). C12 poisons the anchor with an empty page and then never alerts at all (a false **`clean`**). C12 is graded Critical on §6.4's explicit "a false 'clean' on an actual attack pattern" clause; C11 is Critical because it is a **data-integrity** failure — the system's trust anchor is a lie — not merely because it is noisy. W1-A reproduced C11 through the live Docker worker; W1-C reproduced it independently through the real function bodies on a scratch database. Two methods, one defect.

### 2.2 HIGH (27)

| # | ID | Title | Subsystem | Source | Proposed remedy category |
|---|---|---|---|---|---|
| H1 | **[AUDIT-3-1](#audit-3-1)** | A generic banner-fallback selector clicks a non-banner control that navigates into a Cloudflare interstitial, captured with `cloudflare_challenge_detected: False` and `capture_quality: "full"` | `worker/banner_dismiss.py`, `fetcher.py` | P3 (Session A) | Re-validate the challenge gate after any click; make the fallback selector-specific |
| H2 | **[AUDIT-3-4](#audit-3-4)** | Non-atomic artifact writes that run *before* the DB commit leave a truncated `page.html` behind a row still reading `completed`; nothing ever deletes a `Scan` or `Baseline` row | `worker/artifacts.py`, `scan_tasks.py` | P3 (Session A) | Write-then-rename; move storage after commit; add retention |
| H3 | **[AUDIT-2-4](#audit-2-4)** | `NOISE_FLOOR`/`MATERIAL_CHANGE_RISK` overfitting, now a **measured alert rate**: 36 of 323 benign rows in the model's own training data reach 0.40, **34 exceed the flag threshold**; `vendor_script_added` (benign) averages 0.7538 | `worker/detection/fusion.py` | P2 (Session A) | Re-derive the constant from a benign population including the 7 omitted axes; assert max-per-axis in the corpus validator |
| H4 | **[AUDIT-4-2](#audit-4-2)** | Layer 6 reads **current-side** probe transients as measured evidence: a TLS failure fuses to **0.5502** — above the default flag threshold | `worker/probe.py`, `detection/metadata.py` | P4 (Session A) | Treat current-side probe failure as a degraded channel, not evidence of change |
| H5 | **[AUDIT-4-5](#audit-4-5)** | Empty/unparseable captures are a measured 1.0 (binary junk → risk 0.9833 → `flagged`); **both sides empty reads `clean`**, inverting the system's own "provably zero vs unmeasured" distinction | `worker/detection/*` | P4 (Session A) | A content-type/parseability guard; refuse the `clean` verdict on an empty pair |
| H6 | **[AUDIT-4-4](#audit-4-4)** (AUDIT-8-10, AUDIT-8-11) | Over-broad suppression permanently blinds layers 2/3/5/8 with **no coverage signal**; the `bbox` rule type blinds layer 4 too (conclusive defacement → 0.1372 `changed`) | `worker/detection/suppress.py:87-169` | P4 · P8 (W1-B) | Emit a per-rule coverage fraction in evidence and the UI; scope/limit `bbox` rules |
| H7 | **[AUDIT-8-14](#audit-8-14)** (AUDIT-8-12, AUDIT-5A-2, AUDIT-5A-3) | **Layer 4 has no notion of *why* pixels differ.** A legitimate webfont swap flags at **0.9995 — louder than the glyph hijack it is paired with**; a responsive breakpoint change with byte-identical HTML flags at **1.0000**; a 0.65% height delta on BBC News flags at 0.7633 | `worker/detection/visual.py` | **P8 (W1-B) · P5A (W1-A) — NEW CLASS** | A `capture_context` channel on `PageData` (viewport, device class, colour scheme, font stack) that fusion treats as *explanation*; see O-8-1 |
| H8 | **[AUDIT-SA2-1](#audit-sa2-1)** (AUDIT-8-15, AUDIT-5A-1) | Layer 3 has **no notion of element identity**, so a rotating third-party widget scores identically to a brand-new injection. Measured live: ad/prebid host rotation predicts `1-exp(-0.9)=0.5934` and measures **exactly 0.5934** | `worker/detection/dom.py:640-734` | P4 (Session A) · P8 · P5A | Element-identity-aware ref diff; classify `src` rotation as a value change; recalibrate the additive weights |
| H9 | **[AUDIT-SA1-2](#audit-sa1-2)** (AUDIT-5B-1, AUDIT-5B-2, AUDIT-5A-7, AUDIT-5A-4) | `looks_like_challenge_page` recognises **Cloudflare markers only** and the scan path has no `http_status` gate. 6 non-Cloudflare walls stored as `capture_quality: "full"`; **58% of Tier B's real consecutive-visit pairs FLAGGED** with no attack present | `worker/fetcher.py:166-201`, `scan_tasks.py:262-272` | P4 (Session A) · P5A/P5B (W1-A) | A vendor-agnostic wall-page classifier as a separate gate; an `http_status >= 400` gate on the scan path |
| H10 | **[AUDIT-4B-1](#audit-4b-1)** | Alert/remediation creation is unreachable on the redelivery path — a worker death in the post-commit window loses the alert permanently (window measured at 10.1 ms median / 26.8 ms max; the DB-hiccup variant is unbounded) | `worker/scan_tasks.py` | P4B (Session A) | Create the alert row inside the terminal transaction; a recovery sweep for completed-and-alertless scans |
| H11 | **[AUDIT-4D-1](#audit-4d-1)** | A mid-delivery crash permanently orphans every channel after the crash point — **now deterministically reachable from a CR/LF in a user-controlled site name**; the resweep predicate can never re-arm it | `worker/alert_tasks.py` | P4D (Session A) | Per-channel delivery rows created up front; fix the resweep predicate to include zero-row partials |
| H12 | **[AUDIT-4E-8](#audit-4e-8)** | Heuristic redaction lets a 9-character custom-endpoint key survive into the dict persisted as layer-8 `ScanFinding.evidence` and into an HTTP 503 body — **reaching a Viewer** | `app/llm.py:60-79` | P4E (Session A) | Value-aware redaction against the configured key set, not shape heuristics |
| H13 | **[AUDIT-4E-10](#audit-4e-10)** | `pnpm audit --audit-level high` is now **exit 1** with 2 HIGH `undici` advisories, and the deployed `walkthrough/` tree has **no audit gate at all** | `frontend/package.json`, `walkthrough/` | P4E (Session A) | Bump `vitest` ≥4.1.11; add the same gate to the `walkthrough` workflow |
| H14 | **[AUDIT-SA3-1](#audit-sa3-1)** | The dispatcher's schedule claim is never released: a single broker blip becomes a **silent one-interval scan gap**, and the tick's stats contain no error/lost-publish bucket | `worker/beat_tasks.py:160-221` | P4B (Session A) | Mark the freshly-inserted row failed on publish failure; add a `lost_publish` counter |
| H15 | **[AUDIT-SA3-2](#audit-sa3-2)** | **No retention policy exists** for scans, findings, artifacts, alerts, deliveries, remediation executions, or the audit log — monotonic growth on a product premised on unattended months-long operation | absence of any deletion path | P4B (Session A) | Time-bounded retention per table with a documented horizon; a scheduled prune with per-run budgets |
| H16 | **[AUDIT-SA3-3](#audit-sa3-3)** | A failed capture orphans its artifact tree permanently — the janitor keys on row *existence*, not row *state* or age | `worker/beat_tasks.py:271-291` | P4B (Session A) | Key the janitor on state and age |
| H17 | **[AUDIT-SA3-4](#audit-sa3-4)** | The worker's broker publish has no fail-fast bound: **10.7 s on the first failure, 63.8 s on every subsequent one** — an infra blip becomes wasted scan capacity | `worker/celery_app.py` | P4B (Session A) | Give the worker publisher the same bounded retry policy as the API client |
| H18 | **[AUDIT-8-8](#audit-8-8)** | `<base href>` and same-origin event-handler payloads are invisible to layer 3, which resolves references against `PageData.final_url` rather than the document's own base | `worker/detection/dom.py:596-676` | **P8 (W1-B) — NEW** | Resolve refs against the document base; add `base_href` and `on*`-target collectors |
| H19 | **[AUDIT-8-13](#audit-8-13)** | Legitimate large content and layout changes flag: 40 added articles, an A/B hero swap, a grid redesign and a one-paragraph edit all alert | `worker/detection/*` | **P8 (W1-B) — NEW** | A third verdict state; gate `changed` on the content-layer peak excluding l1 **and** the generic churn term (O-SA-9) |
| H20 | **[AUDIT-9-2](#audit-9-2)** (OPS-1) | `update.ps1` performs **no `.env` reconciliation at all** — the brief's premise of a broken merge was itself wrong, which strengthens the finding. The live `.env` is already **14 documented keys behind** `.env.example` | `scripts/update.ps1`, `.env.example` | **P9 (W1-C) — NEW** | One shared `Get-WardressEnv` primitive; reconcile on update |
| H21 | **[AUDIT-9-3](#audit-9-3)** (OPS-2) | `validate.ps1` green-lights a memory configuration the measured deployment cannot survive — the `< 4 GB` check **does not fire at all** on this host (`7.4 -lt 4` → `False`), while 12 warm children are 79% of the ceiling. No disk or port checks either | `scripts/validate.ps1` | **P9 (W1-C) — NEW** | Check Docker's `MemTotal`, not the host's; add disk and port preflight |
| H22 | **[AUDIT-9-4](#audit-9-4)** (OPS-4) | `diagnostics.ps1` **does not scrub the product's own `wk_` API keys** — 9 of 16 hostile shapes escape a bundle the script tells the user is safe to share (incl. JWTs, Fernet keys, Apprise URLs) | `scripts/diagnostics.ps1` | **P9 (W1-C) — NEW** | Extract the rule table into a tested module; run a hostile corpus in CI (O-9F) |
| H23 | **[AUDIT-9-5](#audit-9-5)** (OPS-5) | The documented restore path silently downgrades the schema below the running binary and **reports success on a partial load** | `scripts/uninstall.ps1` backup/restore | **P9 (W1-C) — NEW** | Pin the schema revision in the backup; verify-and-fail on a partial restore |
| H24 | **[AUDIT-6-2](#audit-6-2)** | The worker leaks **exactly 2.0 zombie processes per scan cycle, linearly and without bound** (1,444 → 1,546 over a 50-cycle soak) | `worker` child reaping | **P6 (W2) — NEW** | Reap children; or bound the soak-visible process table growth |
| H25 | **[AUDIT-6-3](#audit-6-3)** | Scan cost inflates **9–16× at full concurrency** while throughput improves only 1.3–1.6×; **83–94% of the wall clock is outside the capture** (12 children × 6 torch threads on 6 cores) | `worker/detection/semantics.py`, worker config | **P6 (W2) — NEW** | `torch.set_num_threads(1)` per child; batched MiniLM (O-SA-2) |
| H26 | **[AUDIT-7-2](#audit-7-2)** | The metadata probe has **no total deadline**: a 90-second header slow-loris costs **271.9 s — 13.6× its own 20 s budget and 57% of the scan's hard time limit** | `worker/probe.py` | **P7 (W2) — NEW** | A wall-clock deadline across the whole probe, not per-operation |
| H27 | **[AUDIT-7-3](#audit-7-3)** (NB-CAP-1) | `probe.py` buffers the **entire** hostile response before slicing: peak heap scales linearly with attacker-chosen body size and is unbounded (+13.9 / +50.4 / +141.1 MB for 10 / 60 / 200 MB) | `worker/probe.py:170,223` | **P7 (W2) — NEW** | Stream with an incremental cap; abort past the limit |

### 2.3 MEDIUM (79)

Presented in subsystem groups for readability; severity is uniform (Medium) throughout.

**Capture & stealth**
| ID | Title | Source |
|---|---|---|
| [AUDIT-3-2](#audit-3-2) | Late-attaching consent iframes never dismissed (single frame snapshot + a viewport test that never scrolls into view: `y=78.4` dismissed, `y=2578.4` not) | P3 |
| [AUDIT-3-3](#audit-3-3) | SSRF rebinding window on the Playwright path; the verdict cache key omits the port — **largely subsumed by C1** | P3 |
| [AUDIT-3-5](#audit-3-5) | Capture-completeness facts never reach detection — **17 of 19 `capture_evidence` keys have zero production readers** | P3 |
| [AUDIT-SA1-4](#audit-sa1-4) | `apply_stealth` fails open only when the package is *absent*; a raising library strands the scan row in `running` | P4 (SA) |
| [AUDIT-5A-5](#audit-5a-5) (AUDIT-7-4) | A transient DNS failure is surfaced as `SSRFBlockedError`, which the retry contract **permanently excludes from retrying**; a blackholed resolver freezes the event loop for 8.004 s | P5A · P7 |
| [AUDIT-5A-6](#audit-5a-6) | The mandated stress runner **cannot detect the failure mode Tier B exists to catch** — it records a bot-wall capture as a clean PASS | P5A |
| [AUDIT-5B-4](#audit-5b-4) | `net::ERR_HTTP2_PROTOCOL_ERROR` is classified TRANSIENT and retried, and still fails 3/3 | P5B |
| [AUDIT-5B-5](#audit-5b-5) | Catalog category drift, measured and timestamped (15 rows) — logged per the catalog's own protocol | P5B |
| [AUDIT-5C-2](#audit-5c-2) (AUDIT-5B-3) | The height-only screenshot guard fails on 7 of 52 Tier B/C sites; widths of 4,000 px and 1,378 px captured uncapped with `capture_quality: "full"` | P5B/P5C |
| [AUDIT-5C-3](#audit-5c-3) | Pages whose scrollable content lives in an inner container are captured as a single viewport and reported `full` | P5C |
| [AUDIT-5C-4](#audit-5c-4) | `apnews.com` reproduces the scroll-shrink path live: `initial_height 15368 → final_height 768`, still reported `full` (confirms AUDIT-3-8) | P5C |
| [AUDIT-5C-5](#audit-5c-5) | `india.gov.in` returns 403 to Wardress's browser but 200/607 KB to Wardress's own probe — the block is on the browser client, not the UA | P5C |

**Detection**
| ID | Title | Source |
|---|---|---|
| [AUDIT-2-1](#audit-2-1) | Taxonomy gaps: three attack families genuinely absent from the corpus | P2 |
| [AUDIT-2-3](#audit-2-3) | Redirect-based cloaking and staged/time-delayed payloads — **the redirect half is now largely closed by real renders** (see §4) | P2 |
| [AUDIT-2-5](#audit-2-5) | `ScanFinding` has no `degraded` column, so a findings-only consumer cannot tell "provably zero" from "dark channel" | P2 |
| [AUDIT-4-3](#audit-4-3) | A statically expired certificate scores 0.5 on **every** scan → fused 0.4857, verdict `changed` forever, permanently inside the LLM escalation band | P4 |
| [AUDIT-4-6](#audit-4-6) | Layer 3 is removal-blind (all five reference kinds score exactly 0.0) — **the higher-severity halves escalated to C8** | P4 |
| [AUDIT-4-7](#audit-4-7) | Specification: how layers should consume capture-completeness flags (narrowed — layer 4 already top-crops) | P4 |
| [AUDIT-4-8](#audit-4-8) | Specification: which layers consume linked-stylesheet bytes (hidden-state resolution is already symmetric per side) | P4 |
| [AUDIT-2B-1](#audit-2b-1) | External stylesheet bytes are never captured — stylesheet-hidden content is invisible to every DOM-based layer | P2B |
| [AUDIT-2B-2](#audit-2b-2) | Sub-threshold emission gaps persist and their corpus rows were **dropped**, so no standing guard covers them | P2B |
| [AUDIT-SA2-4](#audit-sa2-4) | `sanity_benign_quiet` fuses to 0.6583; layers 1/2/3/6/8 are individually incapable of reaching 0.40 | P4 (SA) |
| [AUDIT-8-9](#audit-8-9) | A defacement inside `<noscript>` is invisible to Wardress's own screenshot; a `title=` tooltip payload is invisible to every channel | P8 (W1-B) |
| [AUDIT-8-11](#audit-8-11) | A suppression rule that times out manufactures the delta it was meant to silence (isolated with a clean control) — **merged into H6** | P8 (W1-B) |
| [AUDIT-9-6](#audit-9-6) | Every `<link href>` scores 0.6 regardless of `rel`, so five routine relations are indistinguishable from a stylesheet hijack | P9 (W1-C) |

**Orchestration, scheduling & data**
| ID | Title | Source |
|---|---|---|
| [AUDIT-1-2](#audit-1-2) | The below-target Phase-13 capture categories were closed with aggregate attributions, not the per-site root causes Rule 19 demands | P1 |
| [AUDIT-4B-2](#audit-4b-2) (AUDIT-6-5) | Overload amplification — **confirmed live and worse than predicted**: the trigger is *age*, not backlog depth; supersession fires at K=5, 15, 30, 60 alike | P4B · P6 |
| [AUDIT-4B-3](#audit-4b-3) | Adaptive cadence consumes raw fused risk without the degradation signal; **4 consecutive clean scans** are needed to return to base, so a daily-transient site never returns | P4B |
| [AUDIT-4B-5](#audit-4b-5) | Stale-row recovery is bounded by `next_scan_at` (worst case 24 h 20 min); **stuck baselines have no beat-side stale sweep at all** — the site is permanently unmonitored with no signal | P4B |
| [AUDIT-4B-6](#audit-4b-6) | The beat heartbeat is written on the success path only, so any dispatcher failure turns the operator's only scheduling signal red | P4B |
| [AUDIT-SA3-5](#audit-sa3-5) | A failing `_schedule_next` silently converts a site into a once-per-tick scan loop | P4B (SA) |
| [AUDIT-SA3-6](#audit-sa3-6) | The in-flight unique index firing inside the dispatcher is absorbed into no stats bucket | P4B (SA) |
| [AUDIT-SA3-8](#audit-sa3-8) | Migrations run only from `install.ps1`/`update.ps1`, never at container start | P4B (SA) · P9 |
| [AUDIT-SA3-10](#audit-sa3-10) | `missing-prereqs` is the only scan-failure path that leaves `verdict` NULL | P4B (SA) |
| [AUDIT-SA3-11](#audit-sa3-11) | `pool_pre_ping=True` is unreachable and every Celery task pays ~88 ms to build and tear down an engine (measured 95.06 fresh vs 5.32 ms pooled) | P4B (SA) · P9 |
| [AUDIT-6-4](#audit-6-4) | At 5× the failure rate is highly non-deterministic: **0/60 → 8/60 → 17/60 across three identical passes** | P6 (W2) |
| [AUDIT-7-5](#audit-7-5) | A worker SIGKILL leaves the scan row `running` forever; **the broker does not redeliver** (`task_reject_on_worker_lost` defaults False) | P7 (W2) |
| [AUDIT-2B-3](#audit-2b-3) | Remediation claim "crash-after-claim" window: an executor crash leaves a terminal `confirmed` row that is never re-runnable | P2B |

**Alert & remediation delivery**
| ID | Title | Source |
|---|---|---|
| [AUDIT-4D-2](#audit-4d-2) | Alert delivery's idempotence guard is check-then-act, not an atomic claim | P4D |
| [AUDIT-4D-3](#audit-4d-3) | The favicon resolver fetches through an unpinned httpx client | P4D |
| [AUDIT-4D-4](#audit-4d-4) | "Downloads are size-capped (64 KiB)" is not delivered — a 32 MiB body produces a 64.2 MiB heap peak before truncation | P4D · P9 |
| [AUDIT-4C-1](#audit-4c-1) | Single-site create with a dead broker answers 503 after the site is already committed; the invited retry 409s | P4C |
| [AUDIT-2B-4](#audit-2b-4) | `imports.py` still enqueues baseline captures synchronously on the event loop | P2B |

**API, auth & rate limiting**
| ID | Title | Source |
|---|---|---|
| [AUDIT-4C-2](#audit-4c-2) (AUDIT-9-15) | `/docs`, `/redoc`, `/openapi.json` **and `/docs/oauth2-redirect`** are public and unmetered; the 92,500 B schema narrates the SSRF gate | P4C · P9 |
| [AUDIT-SA4-1](#audit-sa4-1) | A password reset does not invalidate outstanding access tokens and does not revoke API keys — exactly one of three credential classes dies | P4C (SA) |
| [AUDIT-SA4-2](#audit-sa4-2) (AUDIT-9-12) | The per-IP rate limiter is fully bypassable by a client-supplied `X-Forwarded-For` under the *documented* configuration (8/8 allowed); IPv6 is not normalised | P4C (SA) · P9 |
| [AUDIT-SA4-3](#audit-sa4-3) | The per-account login lockout is an unauthenticated, effectively permanent DoS — one request per 15 min holds it indefinitely | P4C (SA) |
| [AUDIT-SA4-4](#audit-sa4-4) | The account lockout is a **user-enumeration oracle**: the 401→429 transition after exactly 5 requests requires no timing analysis | P4C (SA) |
| [AUDIT-SA4-5](#audit-sa4-5) | `CORS_ALLOWED_ORIGINS=*` reflects any origin with `Access-Control-Allow-Credentials: true`, contradicting the stated contract | P4C (SA) |
| [AUDIT-SA4-8](#audit-sa4-8) | `GET /api/sites` is unbounded and silently ignores `limit`/`offset`: 600 sites = 364,581 bytes in one response | P4C (SA) |
| [AUDIT-SA4-9](#audit-sa4-9) (AUDIT-9-13, AUDIT-4C-5) | `GET /api/health` returns **200 in both the healthy and the database-down branch**, so status-code probes report healthy through a total DB outage | P4C (SA) · P9 |
| [AUDIT-9-14](#audit-9-14) | `celery_app.py`'s "acknowledge late so a crashed worker never silently drops a scan" is **false** | P9 (W1-C) |

**AI & supply chain**
| ID | Title | Source |
|---|---|---|
| [AUDIT-4E-3](#audit-4e-3) | A hung provider stalls its caller **one full 30 s timeout per key/deployment** (6 passes: 31.61/30.05/30.03/31.39/30.03/30.08 s) | P4E |
| [AUDIT-4E-5](#audit-4e-5) | Every runtime image is a floating tag; the worker's MiniLM weights are an unpinned floating reference whose failed pre-download is swallowed by `\|\| echo` | P4E (SA) |
| [AUDIT-4E-11](#audit-4e-11) (AUDIT-9-9) | The backend CI job cannot report success: `ruff check .` fails on the **first** command (9 errors), so `ruff format --check`, `pip-audit`, `check_torch_osv` and `pytest` **never execute** | P4E · P9 |
| [AUDIT-SA5-3](#audit-sa5-3) | No Fernet key ring or version prefix: rotating the key **silently destroys** every stored credential and the AI layer then keeps working *with no credential at all* | P4E (SA) |
| [AUDIT-SA5-4](#audit-sa5-4) | **Neither Dockerfile is built in CI at all**, and `walkthrough/` has no audit, lint, typecheck or test gate | P4E (SA) |
| [AUDIT-SA5-2](#audit-sa5-2) | `litellm` logs the full LLM prompt and raw response in plaintext at DEBUG, and `turn_off_message_logging` is never set | P4E (SA) |

**Frontend**
| ID | Title | Source |
|---|---|---|
| [AUDIT-1-1](#audit-1-1) | "Changed, not clean" on benign dynamic content — **downgraded** to Medium with justification; the logged cause was the minor part, and the proposed remedy would not have worked | P1 (SA) |
| [AUDIT-4F-2](#audit-4f-2) | A scan whose detection channels went **dark** renders with the same vocabulary as a measured-identical scan; `consecutive_degraded_scans` is read by **zero** files | P4F |
| [AUDIT-4F-3](#audit-4f-3) | 6 of 19 malformed payload shapes blank the whole dashboard, at 3 unguarded expressions across 4 of 10 routes | P4F |
| [AUDIT-SA4-6](#audit-sa4-6) | Zero `aria-live`/`role="status"` regions anywhere in `src/` — polling state changes are never announced | P4C (SA) |
| [AUDIT-SA4-7](#audit-sa4-7) | Keyboard users cannot use the bulk-import CSV control; three `<Label>` elements label nothing; no data table has a caption | P4C (SA) |
| [AUDIT-9-7](#audit-9-7) | Three code comments assert a 0.35 material-change bar (the constant is 0.40) and the benign-risk comment is **10× off** | P9 (W1-C) |
| [AUDIT-9-8](#audit-9-8) | The ReDoS guarantee is enforced for user suppression rules, **absent for the normaliser that runs on every scan**, and the docs read as global | P9 (W1-C) |

### 2.4 LOW (44)

| Subsystem | IDs |
|---|---|
| Capture | [AUDIT-3-6](#audit-3-6) per-scan request multiplication × adaptive cadence = WAF escalation · [AUDIT-3-7](#audit-3-7) latent `content_sha256(None)` crash + a provably dead TLS-parsing branch · [AUDIT-3-8](#audit-3-8) `auto_scroll_page` counts a shrinking height as stable · [AUDIT-SA1-3](#audit-sa1-3) `dismiss_banners` burns ~3.09–3.14 s on every banner-free capture (~28% of a 10.4–11.1 s capture) · [AUDIT-SA1-5](#audit-sa1-5) the screenshot guard is dimension-asymmetric (caps height only, no width key) · [AUDIT-5A-8](#audit-5a-8) `archive.org`'s `noscript` fallback stored as a complete capture · [AUDIT-5A-9](#audit-5a-9) runner budget exhaustion / a site lost to the DNS outage |
| Detection | [AUDIT-2-6](#audit-2-6) `capture_meta["headers"]` has one write and no reader |
| Orchestration | [AUDIT-2B-6](#audit-2b-6) stale dependency declarations · [AUDIT-4B-4](#audit-4b-4) re-baseline does not arbitrate in-flight scans (**accepted-risk is correct — recorded so it is not re-litigated**) · [AUDIT-4B-7](#audit-4b-7) worker memory ceiling, no child recycling · [AUDIT-4B-8](#audit-4b-8) deployment drift → **file-drift half INVALIDATED**, residual only (AUDIT-9-17) · [AUDIT-SA3-7](#audit-sa3-7) `beat` declares no `depends_on: db` (AUDIT-9-11) · [AUDIT-SA3-9](#audit-sa3-9) `via` accepted and discarded by three service functions · [AUDIT-SA3-12](#audit-sa3-12) `wardress.ping` is an orphan registration; every task result is stored in Redis 24 h for a consumer that does not exist · [AUDIT-SA3-13](#audit-sa3-13) Redis runs with no AOF and no `maxmemory` · [AUDIT-6-6](#audit-6-6) Chrome Desktop UA / model-catalog task-naming drift |
| API/frontend | [AUDIT-4C-3](#audit-4c-3) two mute implementations with divergent audit snapshots · [AUDIT-4C-4](#audit-4c-4) `DELETE /api/sites/{id}` has no in-flight guard and no cascade disclosure · [AUDIT-4C-5](#audit-4c-5) readiness docstring cites a dead healthcheck (→ AUDIT-9-13) · [AUDIT-4C-6](#audit-4c-6) three routes double-charge the per-user rate limit (effective budget 10 of 20) · [AUDIT-4C-7](#audit-4c-7) `DELETE /api/users/{id}` hard-deletes regardless of usage, with no UI caller · [AUDIT-2-6](#audit-2-6) · [AUDIT-2B-5](#audit-2b-5) stale gauge comment (now closed into an executable guard) · [AUDIT-4F-1](#audit-4f-1) `capture-health.test.tsx` flake — measured at exactly 1000 ms, load-independent · [AUDIT-4F-4](#audit-4f-4) severity colour defined eight ways · [AUDIT-4F-5](#audit-4f-5) `risk-gauge.tsx` asserts a moved constant · [AUDIT-4F-6](#audit-4f-6) bidi isolation / language marking · [AUDIT-4F-7](#audit-4f-7) unnamed `role="application"` gauge · [AUDIT-4F-8](#audit-4f-8) unconditional-red unmeasured risk chip · [AUDIT-4F-9](#audit-4f-9) duplicate scan-list fetch on two timers · [AUDIT-SA4-10](#audit-sa4-10) 12 dead client functions leave 11 admin routes caller-less · [AUDIT-SA4-11](#audit-sa4-11) initial JS payload 1,077 kB / 404 kB gzip vs 268 kB / 83 kB with a route-level split · [AUDIT-SA4-12](#audit-sa4-12) the audit-log `actor` filter treats `%` and `_` as LIKE wildcards · [AUDIT-SA4-13](#audit-sa4-13) four dead symbols and a degraded predicate duplicated across two routers |
| AI/infra | [AUDIT-4E-6](#audit-4e-6) the Ollama default endpoint is a Docker-only constant with a self-contradicting fallback chain · [AUDIT-4E-7](#audit-4e-7) the model-pull stream has no deadline of any kind · [AUDIT-4E-9](#audit-4e-9) dependency-hygiene residue · [AUDIT-SA5-5](#audit-sa5-5) `.dockerignore` excludes git-tracked ignores, baking local scratch logs into the shipped image · [AUDIT-SA5-6](#audit-sa5-6) both runtime images run as root with no `cap_drop`/`read_only`/`no-new-privileges` · [AUDIT-SA5-6b](#audit-sa5-6b) alert delivery has no retry and no circuit breaker under a provider outage · [AUDIT-SA5-7](#audit-sa5-7) `LOGIN_RATE_LIMIT_PER_IP` is read by the code, exercised by tests, and documented in **neither** file (and compose never forwards it, so it is unsettable) · [AUDIT-SA5-7b](#audit-sa5-7b) remediation webhook payloads carry no authentication and no replay protection · [AUDIT-SA5-8](#audit-sa5-8) `actions/checkout` leaves `persist-credentials` at its default |
| Ops/docs (W1-C) | [AUDIT-9-10](#audit-9-10) three dead entry points the code-walking method cannot reach · [AUDIT-9-16](#audit-9-16) `lib.ps1` has a Windows argument-quoting bug no current caller can reach · [AUDIT-9-17](#audit-9-17) the beat schedule file lives in the container's writable layer and is undocumented |

---

## 3. DEDUPLICATION MAP (what collapsed, and why)

| Canonical finding | Merged duplicates | Why they are the same finding |
|---|---|---|
| **AUDIT-SA1-1** (C) | AUDIT-5C-6 | W1-A found a *controlling* Service Worker on `web.whatsapp.com` under the production context. Same defect, same file, live confirmation rather than a new defect. |
| **AUDIT-5C-1** (C) | AUDIT-9-1 | Two **independent** reproductions of one defect: W1-A through the live Docker worker (risk 0.99999), W1-C through the real `capture_baseline`/`run_scan` bodies on a scratch DB (risk 0.9999999999997338). |
| **AUDIT-7-1** (C) | *(none)* | Same *missing gate* as 5C-1 but the **opposite** failure direction (false `clean`, not false `flag`). Kept separate because the fix shape and the severity clause differ. |
| **AUDIT-SA2-3** (C) | AUDIT-8-4 | W1-B sharpened the mechanism: the score is a **step function of page size** (0.10–0.13 small, exactly 0.0 on realistic pages), which is the same scale-blindness with a sharper description. |
| **AUDIT-SA2-2** (C) | AUDIT-8-1, AUDIT-8-2 | W1-B confirmed the false `clean` and extended it: a `<meta http-equiv>` CSP is never read at all, and HSTS neutralisation is the same "no direction classifier" defect. |
| **AUDIT-4-1** (C) | AUDIT-8-6 | W1-B **extended the blast radius**: the collapse also false-flags *punctuated* pages, so the "unpunctuated pages only" mitigation does not hold. |
| **AUDIT-8-5** (C) | AUDIT-8-7, half of AUDIT-4-6 | Removal-blindness and un-hiding-blindness are the two directions of one bidirectional-diff defect. Escalated Medium→Critical. |
| **AUDIT-4-4** (H) | AUDIT-8-10, AUDIT-8-11 | W1-B **refined** it: content rules do *not* blind layer 4 (they reduce rather than suppress), but the `bbox` type is total. The escalation is preserved. |
| **AUDIT-SA2-1** (H) | AUDIT-8-15, AUDIT-5A-1 | Three independent measurements of one missing element-identity notion, including an *exact* predicted-vs-measured match (0.5934). |
| **AUDIT-8-14** (H) | AUDIT-8-12, AUDIT-5A-2, AUDIT-5A-3 | One new class: layer 4 has no *explanation* channel, so benign visual changes flag louder than the attacks they were paired with. |
| **AUDIT-3-4** (H) | AUDIT-SA3-3 | The retention half of the artifact-lifecycle defect, from the orchestration side. |
| **AUDIT-SA3-2** (H) | AUDIT-SA3-13, AUDIT-SA5-5 | The retention class (XS-4): unbounded growth in every store the product writes to. |
| **AUDIT-SA1-2** (H) | AUDIT-5B-1, AUDIT-5B-2, AUDIT-5A-7, AUDIT-5A-4 | W1-A's per-site wall evidence and the 58% Tier-B false-flag rate are the live instance of Session A's predicted detector defect. |
| **AUDIT-5A-5** (M) | AUDIT-7-4 | W2 reproduced W1-A's live observation and root-caused it to `ssrf.py:55-58`, plus found the event-loop freeze. |
| **AUDIT-4B-2** (M) | AUDIT-6-5 | W2 ran the overload live (Session A deliberately did not) and found the trigger is *age*, not backlog depth. |
| **AUDIT-3-8** (L) | AUDIT-5C-4 | `apnews.com` reproduces the scroll-shrink path live. |
| **AUDIT-4E-11** (M) | AUDIT-9-9 | The same dead CI gate, re-measured exactly (9 errors, same file, same rule). |
| **AUDIT-4C-2** (M) | AUDIT-9-15, AUDIT-4C-5 | The public-schema exposure, re-measured live at 92,500 B with the fourth route confirmed at 3,012 B. |
| **AUDIT-SA4-9** (M) | AUDIT-9-13, AUDIT-4C-5 | `/api/health` returns 200 in both branches — the concrete form of the docstring drift. |
| **AUDIT-SA3-7** (M) | AUDIT-9-11 | `beat` has no `depends_on: db`; three of seven services have no healthcheck. |
| **AUDIT-4B-8** (L) | AUDIT-9-17 | The file-drift half was **invalidated** (57/57 file comparisons matched); the residual is the undocumented beat schedule file. |
| **AUDIT-4E-8** (H) | *(severity escalation)* | Medium→High after W-1 re-measurement showed the leak reaches a Viewer via layer-8 evidence and an HTTP 503 body. |
| **AUDIT-4E-10** (H) | *(severity escalation)* | Low→High: the gate status changed from "2 moderate, exit 0" to **exit 1 with 2 HIGH**. |

**Not merged, deliberately:** AUDIT-7-1 with AUDIT-5C-1 (opposite failure direction, different fix clause); AUDIT-8-3 with AUDIT-8-14 (area floor vs missing explanation channel — different mechanisms inside one layer); AUDIT-6-1 with AUDIT-6-2 (OOM cascade vs an unbounded leak — one is a bound, the other is the absence of one).

---

## 4. CLAIMS THIS AUDIT INVALIDATED, CORRECTED, OR COULD NOT REPRODUCE

Recorded because a remediation author must not act on a number this audit has shown to be wrong.

**Invalidated outright (do not spend remediation effort here):**
| Claim | Disposition |
|---|---|
| "Fusion reload is a bottleneck" | **INVALIDATED** — 0 `json.loads` across 6,000 `layer9_fusion()` calls; 0.0135 ms/call; cached per process, and `_model_lock` cannot contend across processes. |
| O-SA-3 "resize once per layer-4 call" | **INVALIDATED** — the sign flips between two plausible screenshot heights: **+34.3 ms (9.5%)** at 1280×3000, **−21.9 ms (−3.6%)** at 1280×4000, n=5+5 interleaved. Do not implement. |
| "Regex compilation cost" | **INVALIDATED** — 17 module-level `re.compile` at import; the hot inline site costs **1.725 µs**. No recompilation anywhere. |
| `AUDIT-2-2`'s "subtle single-word tampering is genuinely absent" | **INVALIDATED** — measured **0.6718 `flagged`**. A one-word edit on a punctuated page **is** caught, via layer 4. |
| `AUDIT-2-3`'s "meta-refresh / `location.replace` cloaking evades" | **REFUTED** — a 0-second meta-refresh fires *during* Playwright capture, so the screenshot is the attacker's page: **1.0000 `flagged`** for both. A *non-zero-delay* refresh would still evade (a corpus gap, not a detection gap). |
| `AUDIT-2-2`'s "only a new-domain phishing overlay is caught" | **INVALIDATED** — same-origin **0.9993 `flagged`** with a real screenshot. |
| `AUDIT-4B-8`'s file-drift half | **INVALIDATED** — 57/57 file comparisons matched across three independent subagents. The "rebuild before verification" prerequisite is **already satisfied**. |
| `AUDIT-4C-2`'s "`wk_` key prefix in the public schema" | **INVALIDATED** — 0 hits across the schema; the prefix lives in `app/apikeys.py`. The finding stands on 8 stronger items. |
| `AUDIT-4-4`'s "60 pathological nodes cost nodes × 2 s" | **INVALIDATED** — one timeout aborts the whole element loop; cost is bounded at ~2.0 s per *rule per side*. Confirmed by W2 independently. |

**Corrected / reconciled:**
| Claim | Correction |
|---|---|
| Session A "layer 8 is 66% of detection cost" vs W1-C "93–95%" | **Both correct at their own scale.** The durable statement: **L8 is bounded by design (saturates at 2.4–3.0 s); layers 2/3/5 are not** (L2: 1.12 → 138.90 ms from 0.3 KB → 171 KB, linear and unbounded). |
| `scan_tasks.py:48` "(~0.03)" benign risk | **~10× too low.** Honest band across both sessions: **0.19–0.30**. |
| OpenAPI schema "92,500 B" and "99,585 B" | **92,500 B is current**; 99,585 B could not be reproduced under any encoding and is **marked superseded**. |
| `AUDIT-4B-2` "amplification begins at 15–60 pending rows" | **Worse than predicted** — the trigger is **age, not backlog depth**; supersession fires at K=5, 15, 30 and 60 alike. |
| `AUDIT-4B-7` "12 warm children can OOM-spiral" | **Verified** — 582.6 MB/child measured, 75.4% of ceiling at the OOM instant, 85.8–87.8% running. But the soak shows worker memory **plateaus** from cycle ~36, so the projection is a *bound*, not a leak. The genuinely unbounded resource is a **different one** (AUDIT-6-2, zombies). |
| `AUDIT-SA2-3` "layer 7 is exactly 0.0" | **Partially refuted, direction confirmed and sharpened** — it is a **step function of page size**, not a flat zero. |
| `AUDIT-4-4` "content rules blind layers 5 and 8" | **Refined** — content rules do not blind layer 4; the **`bbox`** rule type does, and that is the primitive that matters. |
| W1-B's own summary count | Its detail tables show **4 Critical / 9 High / 2 Medium**; its summary line said 5/8/2. The **detail tables are authoritative** and are what this register uses. |

**The single most important methodological note in this audit.** W1-B and Session A report *different numbers for the same fixtures*, and the difference is **method, not product**. Session A's synthetic fixtures had **no screenshots**, so layer 4 was `degraded` and contributed nothing; W1-B ran **real Chromium 149 renders on both sides**, so layer 4 carried signal. **Production always has screenshots.** Where the two diverge, **W1-B's numbers are the more faithful measurement of deployed behaviour**, and the apparently-alarming "Session A was wrong" items above are mostly Session A measuring a *degraded* channel. This is recorded so a remediation author does not read it as two sources in conflict.

---

## 5. CONSOLIDATED OPPORTUNITIES / INNOVATION REGISTER (Rule 17)

Not severity-scored. Consolidated from O-1…O-3 (P1), O-7/O-8 (P2B), O-4D-1…3, O-4E-1…4, and Session A's O-SA-1…13, plus Session B's O-8-1…11, O-9A…F, and W2's.

**Tier 1 — closes a whole defect class with one change (highest value):**
| # | Idea | Closes | Where |
|---|---|---|---|
| O-9A | **A "poisoned anchor" content-shape gate at baseline promotion** — refuse (or flag `suspect`) a candidate baseline whose document is implausibly small relative to its own screenshot, below a visible-text floor, or in the bottom percentile for that site. Vendor-independent: it catches paywalls, consent walls and captchas from *every* vendor, today and tomorrow, for three arithmetic checks on data the capture already produced. | C11, C12 | `worker/scan_tasks.py` |
| O-SA-1 | **One outbound-fetch factory** (`safe_async_client()`) that always installs the pinning transport, plus a test asserting no module builds a bare `httpx.AsyncClient`; and for the browser, one armoured-context constructor that both blocks service workers and installs a context-scoped guard. Makes "forgot the policy" unrepresentable. | C1, C2, C3, H6-adjacent | `app/ssrf_transport.py`, `worker/fetcher.py`, `ai_catalog.py`, `site_icons.py`, `ai_ollama.py` |
| O-8-1 | **A `capture_context` channel on `PageData`** (viewport, device class, `prefers-color-scheme`, declared font stack, resolved `@font-face` sources) that fusion treats as *explanations*, not evidence. Converts "the pixels differ" into "the pixels differ **and nothing else could explain it**" — the only thing that lets layer 4's 26.26 coefficient be defended on a real page. | H7, H8 | `types.py`, `fetcher.py`, `visual.py`, `fusion.py` |
| O-9C | **One `.env` reconciliation primitive shared by install, update, validate and diagnostics** (`Get-WardressEnv` with `Get-RequiredKey`/`Get-MissingKeys -Against .env.example`). Turns the OPS-1 reconciliation into a one-line call instead of a fourth drifted implementation. | H20, H21 | `scripts/lib.ps1` |
| O-9F | **Ship the diagnostics scrubber as a tested module, not a PowerShell literal** — a data-file rule table plus a hostile-corpus test asserting zero escapes. | H22 | `scripts/` |
| O-8-8 / O-SA-12 | **A standing benign-population gate that fails the build** — every benign axis needs ≥8 corpus rows, and `validate()` must assert the **maximum** fused risk per benign axis, not just the attack peak. Converts AUDIT-2-4 from a one-time measurement into a permanent red signal. | H3, H19 | `backend/tools/build_regression_corpus.py` |

**Tier 2 — measured optimisations with a stated payoff:**
| # | Idea | Measured payoff | Note |
|---|---|---|---|
| O-SA-2 | **Batched MiniLM encoding** | **1.76× / −261.7 ms per scan** (W2/W1-C; Session A measured 1.68× / −253 ms) | The single highest-value optimisation found. 24 individual calls 606.8 ms → 1 batched 345.0 ms |
| O-SA-7 | **A process-scoped DB engine for Celery tasks** | **95.06 → 5.32 ms per task (17.9×)** | Makes `pre_ping` and `recycle` meaningful for the first time |
| O-SA-4 | **Event-driven banner wait** + scroll a consent-iframe control into view | **−3.09–3.14 s from every banner-free capture (~28%)** | The largest single capture-latency win; also converts a measured `dismissed: False` into a real dismissal |
| O-SA-5 | **Parallel `probe_site` UA fetches** (`asyncio.gather`) | ~2× on the probe leg | `max_connections=4` is already provisioned and idle for 3 of 4 slots |
| O-8-2 | **Tile-localised layer 4** (grid-cell SSIM/pHash, max or 90th-percentile aggregation) | Fixes the 0.1%/0.5% area cliff; makes a *partial* `@font-face` hijack detectable | Needs a corpus re-baseline — a deliberate trade |
| O-8-5 | **An absolute-mass channel for layer 7** | C6 | Needs the `partial_cloaking_small_payload` axis first |
| O-8-6 | **A CSP source-expression restrictiveness table** | C5 | Turns a set comparison into a comparison; gives the additive direction a correct sign |
| O-8-7 | **A typography/`<base>`/event-handler reference surface for layer 3**, keyed on `tag+index+stable-attr` | H8, H7, H18 | Gives layer 3 the element-identity notion it has never had |
| O-8-3 | **A suppression-coverage meter** (chars/elements removed per rule, in evidence *and* the UI) | H6 | The cheapest possible mitigation for the entire suppression-adversary class |
| O-SA-6 | **Route-level `lazy()` in the SPA** | **1,077 kB / 404 kB gzip → 268 kB / 83 kB** (−809 kB raw / −321 kB gzip) | 205 kB is inlined provider logos; 146 kB is Markdown machinery for 2 of 10 routes |
| O-6-1 | **Bind `torch.get_num_threads(1)` per child** and cap prefork concurrency against the *Docker* ceiling | C13, H25 | 83–94% of the wall clock is thread contention, not capture |
| O-8-4 | **A "what a JS-disabled visitor sees" secondary render** as a low-weight, separately-attributed layer-4 input | AUDIT-8-9 | One extra context with `java_script_enabled=False`; also yields a new *progressive-enhancement diff* signal class |
| O-8-10 | **A `changed_area` evidence field on every layer-4 result** | C7 | Would have made AUDIT-8-3 a one-line diagnosis; costs one extra array |
| O-8-11 | **Cross-check layer 1 against a *structural* hash** (tag counts + ref sets + text shingles) | AUDIT-1-1's unresolved remedy | Makes a hash-gate collision *detectable* rather than merely absent |

**Tier 3 — operator visibility and self-diagnosis:**
| # | Idea | Why |
|---|---|---|
| O-9D | **An operator-facing "expected vs actual scans in 24 h" surface, extended to the anchor** | Would have made C11 self-diagnosing: a permanently-`flagged` site with a week-old unchanged anchor is a *shape*, not a log line |
| O-9B | **Make `looks_like_challenge_page` a vendor registry with a coverage test** | Turns "every vendor in the stress catalog has a registry entry" from an unknown unknown into a tracked gap |
| O-9E | **Make the layer-cost curve a test, not a comment** — assert L8's cost is flat across 30 KB→300 KB while L2's is super-proportional | Makes "layer 2 is what will bite at scale" a checked property. The fusion-reload invalidation is the proof of concept: a two-point A/B killed a plausible optimisation |
| O-SA-3 | — | **WITHDRAWN — measured and invalidated.** Do not implement |
| O-1…O-3, O-7, O-8, O-4D-1…3, O-4E-1…4, O-8-9, O-9C, O-9F | UA-era freshness signal · fleet-level "banners we could not dismiss" aggregation · challenge-gate wait duration in evidence · machine-readable blast-radius manifest · a "comment-asserts-constant" drift spot-check · adversarial fixtures as a first-class committed artifact | Carried forward from earlier phases; unchanged |

---

## 6. WHAT WAS **NOT** TESTED — honest coverage gaps (per §6.3's spirit, stated even here)

1. **Three chaos experiments have 0 passes.** W2's Postgres-restart-mid-scan, Redis-connection-loss and network-partition scenarios were budgeted but not run. They are listed with a recommendation, not silently dropped.
2. **The >10 MB DOM scenario has 1 pass, not 3.** W2 recorded the reason rather than repeating a 3-pass run it could not justify the cost of. Rule 18 is therefore **not fully satisfied for that one scenario**.
3. **The backup → restore end-to-end replay is UNVERIFIED.** Rule 15 forbade running `install.ps1`/`uninstall.ps1`, which would have destroyed the live volumes three sibling subagents were testing against. W1-C substituted static analysis plus a bidirectional artifact-coverage cross-check at **medium-high confidence** and labelled it as such. A remediation prompt should schedule a real replay.
4. **The DB-index `EXPLAIN` sweep is untested at production scale.** W1-C's seed hit a schema mismatch, so both passes returned empty-table plans. N+1 absence was verified by source reading instead.
5. **W1-C did not re-measure Session A's capture-side or frontend performance work** (O-SA-4/5, O-SA-6) — contention territory. Those figures stand on Session A's measurements.
6. **The `DOC-3` "Telegram bot direct DB bypass" diagram is not in the repository.** W1-C searched `docs/**`, `README.md` and the Mintlify skill and found no such claim. If Session A read one, it is not under version control and cannot be audited. Restated as "the claim is not present".
7. **All latency figures from W1-A, W1-B and W1-C were taken under CPU/memory contention** with two or three sibling subagents on a 6-core host. They are labelled as such in each report and should be treated as *relative* comparisons. **W2's numbers were taken with the machine to itself** and are the clean ones.
8. **No remediation was attempted, designed, or specified at the implementation level.** This audit diagnoses. Per §8, the user authors the remediation prompt.

---

## 7. AUDIT STATUS DECLARATION

> ### The PROMPT-003 audit is **COMPLETE**.
>
> All **17 audit phases** have been executed and logged. Phases 1–4F and Session A's deep verification were completed in earlier sessions; Phases 5A, 5B, 5C, 6, 7, 8, 9 and 10 were completed in this session by four subagents and the coordinator respectively. **Nothing is left pending. Every finding carries a disposition.**

**Total finding counts by severity, deduplicated across all 17 phases and two sessions:**

| Severity | Count |
|---|---|
| **Critical** | **13** |
| **High** | **27** |
| **Medium** | **79** |
| **Low** | **44** |
| **TOTAL** | **163** |

*(181 raw entries across 11 reporting units; 18 merged as duplicates; 6 severity escalations applied by later phases.)*

**Dispositions:** 175 of 181 raw entries are **Fix-candidate**; **6 are Accepted-risk**, each individually justified in its own entry. The six are: **AUDIT-1-2** (PROMPT-002's aggregate close-out, now superseded by P5A's per-case work), **AUDIT-4B-4** (re-baseline non-arbitration — Session A's independent re-assessment confirmed accepted-risk is the correct call), **AUDIT-4B-8**'s file-drift half (**invalidated**), **AUDIT-4C-2**'s `wk_` sub-claim (**invalidated**), **AUDIT-5A-9** (runner budget exhaustion, an environment limit), and **AUDIT-6-4**'s 5× non-determinism, which is fully root-caused in the OOM cascade at C13 and therefore disposed as a Fix-candidate of that finding rather than a separate risk. **These are surfaced for the user's accept/reject decision.**

**The three clusters a remediation prompt should sequence first, because each is a single defect class that a phase-by-phase process structurally could not see:**

- **The trust anchor is not trustworthy.** C11 + C12 are one missing gate producing opposite failure directions, reproduced twice by independent methods. A site can be monitored against a paywall, a login wall, or a 39-byte truncated response and the system will not say so — it will either alert forever or never alert at all. This is the single most consequential finding in the audit.
- **The SSRF policy is applied per call site rather than structurally.** C1, C2, C3 (+ H6) are one shape — *someone remembered to add the check* — across four subsystems, with one shared fix.
- **Degradation and "proved nothing" are the same object to every operator-facing surface.** XS-1: six findings, one chain, from 17 of 19 unread `capture_evidence` keys to a dashboard that renders `Clean` / `0%` for a scan that measured nothing.

**Verified-clean results worth recording** (measured, not doc-trusted — these are the parts of the system that held up): the SSRF policy blocked **27/27** redirect and internal-target probes across W2's full matrix; the layer-1 hash gate resisted **10/10** whitespace and normalisation bypass shapes; pipeline determinism is **exact** (pstdev 0.000000 across 273 invocations); churn padding does not dilute an attack (a defacement + 40 articles scores 1.0000); the capture→screenshot path returned a measured layer 4 on **85/85** visual fixtures with zero crashes; `docs.json` navigation is clean in both directions (24/24, zero orphans); and every Session A headline number W1-B re-measured was **confirmed digit-for-digit** (36/34, 0.7538/0.8269, 0.6583, 0/56).

> ### This is **not** a Clean Bill of Health.
> §6.3 reserves that for a remediation effort that has closed these findings and re-verified them. 13 Critical and 27 High findings stand open. §8.1's charter thresholds are met on all three counts (any Critical exists; any High exists; ≥3 Medium in the same subsystem), so a remediation prompt is warranted.

**PROMPT-003 does NOT auto-generate PROMPT-004 or any remediation prompt, and this audit has not authored one.** The user will review this register and create their own remediation prompt with whatever scope, architecture and priorities they choose. Per §8.2, that prompt should end in a Re-Audit & Sign-Off phase that re-runs the regression suite, re-executes the stress catalog, and re-verifies every finding using the exact original reproduction — the four characterization test files in `backend/tests/` (150 tests) and W1-B's `test_phase8_adversarial_detection.py` are the durable baseline for exactly that.

---

## 8. FULL REGRESSION RESULTS (Session B)

| Suite | Result | Owner |
|---|---|---|
| Detection 12-file batch | **222 passed** — exact match to the recorded baseline | W1-B |
| Detection 10-file batch + Session A file + new Phase 8 file | **331 passed, 20 xfailed** | W1-B |
| `test_phase8_adversarial_detection.py` (new) | **12 passed, 20 xfailed**, `ruff check` + `ruff format --check` clean | W1-B |
| Full backend suite | **1471 passed, 1 failed, 20 xfailed** | W2 |
| The single failure | `test_confirm_cancel_race_single_winner` — **agent subsystem, not W2's**; passes in isolation. Not a regression from this session. | W2 |
| W1-C | No test files added; zero production files touched | W1-C |
| `pnpm build` / `vitest` / `tsc -b` / `oxlint` | Not re-run by W1-C (out of its assigned subsystem); baselines stand from Session A (144 tests / 0 failed) | — |

**Rule 5 status: no regression.** Every suite is at or above its recorded baseline. The one failing test is a pre-existing flake in an excluded subsystem that passes in isolation.

**New hermetic tests added this session (uncommitted):**

| File | Tests | Covers |
|---|---|---|
| `backend/tests/test_phase8_adversarial_detection.py` | **12 passed, 20 xfailed** | W1-B's Phase 8 fixtures: the visual-only attack/twin pairs, the layer-4 area curve, the layer-1 bypass resistance corpus, the layer-7 scale step function, the ReDoS position-sensitivity matrix, and a re-derivation of the corpus guard (0 of 56 benign rows over 0.40) from the artifact. The 20 `xfail` entries are the **characterization guards** a remediation prompt will flip as it fixes each finding (Rule 5). |
| *(Session A's three files, carried forward)* | **138 passed** | `test_session_a2_detection_findings.py` (107), `test_phase_sa3_orchestration_deep.py` (22), `test_phase_sa5_ai_infra_repros.py` (9) |

**Together: 150 committed-characterization tests** that assert *current* behaviour and are the executable form of the register above.

---

## 9. FINDINGS ROUTED OUT OF SCOPE (recorded, not investigated)

- **AUDIT-SA2-2's** CSP direction classifier remedy needs a token-semantics table — a CSP-spec design question, confined to `worker/detection/metadata.py` (now has a concrete shape: O-8-6).
- **AUDIT-SA2-3's** cloaking re-tune requires the `partial_cloaking_small_payload` corpus axis first (O-8-5, O-8-8).
- **Layer 4's behaviour on live interactive pages at scale** — answered positively by W1-B (L4 0.0031–0.0149, 16× below the bar) but only for a synthetic interactive fixture, not for 121 live sites.
- **W2's three unrun chaos experiments** (§6.1) — recommended for a remediation prompt's own verification phase.
- **The `DOC-3` Telegram-bot diagram** — not present under version control.
- **Ops agent + Telegram surfaces** remain excluded per §0, consistent across every phase.

---

- **Commit**: *pending — the user has not requested a commit. The working tree holds this log entry, four Session B scratch reports, and one new characterization test file. **Zero production files modified across Session B.***

### ✅ PROMPT-003 AUDIT COMPLETE — 17 of 17 phases, 163 canonical findings (13 Critical / 27 High / 79 Medium / 44 Low), every finding disposed. Awaiting the user's own remediation prompt.

