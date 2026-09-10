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

- **Commit**: (filled after commit)
- **Next phase kickoff prompt**: (delivered in chat only — never written to this log)



