# PROMPT-003 — Session A / Subagent 5 — AI Integration, Supply-Chain & Infrastructure Deep Verification

**Scope:** Audit Phase 4E (AI provider integration, supply chain, infra config) + Phase 4D (alert/remediation delivery), re-verified from cold against HEAD `701552e` with the live Docker stack used **read-only**.
**Date:** 2026-09-30
**Rule 1 compliance:** no production code was modified. One new hermetic test file added: `backend/tests/test_phase_sa5_ai_infra_repros.py` (9 tests, all passing, ruff-check- and ruff-format-clean).
**Rule 12 compliance:** `backend/app/ssrf.py` was **read and probed, never edited**. Every SSRF finding below is a *consumer* finding.
**Method note (honest):** the live stack is shared with 4 concurrent subagents. `ruff check .` / `ruff format --check .` counts quoted as "HEAD baseline" were measured at the start of this subagent's work; two files added mid-session by *other* subagents (`test_phase_sa3_orchestration_deep.py`, `test_session_a2_detection_findings.py`) inflate the later counts to 26 files / 28 errors. **My file is not in either list.**

---

## 1. Findings — AI Integration (Phase 4E)

### [DEEPENED] AUDIT-4E-1 — The SSRF policy is skipped by AI providers: a **third, previously-unnamed reader path** exists, and the private-network allowance is keyed on provider *type*
- **Original phase:** PROMPT-003 Audit Phase 4E
- **Severity:** **Critical** — Rule 12 ("any finding here is automatically Critical") + §6.4's SSRF bullet. `app/ssrf.py` is untouched by the proposed remedy.
- **Subsystem / file(s):**
  - Writers of `ai_providers.base_url` (exhaustive, repo-wide grep over `base_url`):
    - `backend/app/ai_config.py:131` `create_provider` — gated on the `validate_url` flag
    - `backend/app/ai_config.py:156` `update_provider` — **always** validates (`:155`)
  - Callers of `create_provider`:
    | caller | base_url | validated? |
    |---|---|---|
    | `app/routers/settings.py:414` (legacy Gemini) | `None` | n/a |
    | `app/routers/settings.py:454` (legacy Gemini key add) | `None` | n/a |
    | `app/routers/settings.py:676` (`POST /api/settings/ai/providers`) | user input | **yes** |
    | `app/routers/settings.py:555-562` (`PUT /api/settings/ollama`, **create** branch) | user input | **NO (`validate_url=False`)** |
    | `app/ai_migration.py:97-104` (legacy migration) | stored `app_settings` row | NO — trusted (documented) |
    | `app/ai_migration.py:140-147` (fresh-install seed) | code constant | NO — documented |
  - Readers that turn `base_url` into an outbound call (**the audit missed #3**):
    | reader | outbound call | consults `assert_url_allowed`? |
    |---|---|---|
    | `app/llm.py:128-141` `_litellm_api_base` → `:144-160` `_deployments` → `resolve_task` (`:283`, used by `worker/llm_escalation.py:60` and `app/explain.py:154`) | litellm Router | **NO** |
    | `app/llm.py:375-390` `validate_provider_call` → `_build_router` (used by `settings.py:512`, `:597`, `:758`) | litellm Router | **NO** |
    | **`app/ai_config.py:234-242` `resolve_tool_capability` → `app/ai_ollama.py:87-104` `show_capabilities`** | **raw `httpx` POST to `{base}/api/show`** | **NO — NEW PATH, not in AUDIT-4E-1** |
    | `app/routers/settings.py:787` `list_ollama_models` | `GET {base}/api/tags` | yes |
    | `app/routers/settings.py:891` `pull_ollama_model` | `POST {base}/api/pull` | yes |
- **Verification method:** code-trace + hermetic test + live read-only probe.
- **Evidence:**
  - New path driven live in a scratch probe: `resolve_tool_capability(None, provider_with_base_url="http://127.0.0.1:6252", "m")` returned `True`, the fake server logged `POST /api/show` with `Authorization: None`, and **no** `assert_url_allowed` call occurred. Caller: `settings.py:823` (`PUT /api/settings/ai/assignments/agent_chat`).
  - Hermetic: `backend/tests/test_phase_sa5_ai_infra_repros.py::test_resolve_tool_capability_never_consults_the_ssrf_policy` — passes.
  - `app/ai_ollama.py:40-46` `normalize_base` performs **no** scheme/credential/address sanitisation: `file:///etc/passwd`, `gopher://127.0.0.1:11211/`, `http://user:pass@internal.example:8080`, `http://[::1]:1`, `http://169.254.169.254:80` all pass through unchanged (measured; pinned by `test_ollama_normalize_base_passes_through_non_http_and_credential_urls`).
  - **The private-network allowance is granted by provider type**, `app/ai_config.py:51`: `allow_private = provider_type in (OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE)`. Under that allowance the SSRF policy **permits the cloud-metadata endpoint** (measured):

    | target | `allow_private=False` | `allow_private=True` |
    |---|---|---|
    | `http://169.254.169.254/latest/meta-data/` | blocked | **ALLOWED** |
    | `http://169.254.169.254/v1/chat/completions` | blocked | **ALLOWED** |
    | `http://100.100.100.200/latest/meta-data/` (Alibaba) | blocked | **ALLOWED** |
    | `http://[fd00:ec2::254]/latest/` | blocked | **ALLOWED** |
    | `http://10.0.0.5/`, `http://127.0.0.1:11434/` | blocked | ALLOWED (intended) |

  - Mechanism (read-only, not proposed for edit): `app/ssrf.py:131-136` — under the opt-in, `_address_blocked` returns `is_multicast or is_unspecified or (is_reserved and not is_global and not is_loopback)`. IPv4 `169.254.0.0/16` is *link-local*, so `is_reserved` is `False` and `is_link_private` is not consulted → not blocked. This is consistent with `ssrf.py`'s own documented "opt-in only loosens" invariant, so **the finding is on the consumer, not on `ssrf.py`.**
- **Deeper analysis:** AUDIT-4E-1 named two unvalidated readers (`validate_ai_provider`, `resolve_task`). Session A adds a third (`resolve_tool_capability`), which is materially different because it is a **raw `httpx` POST** (not a litellm Router call) to a URL that reached the DB through the unvalidated `PUT /api/settings/ollama` create branch — i.e. the two defects compose into a full write-then-fetch chain. It is also the only AI outbound that is **not** rate-limited (`validate_ai_provider` and `pull_ollama_model` both call `enforce_user_rate_limit`; `put_assignment` does not), so it doubles as a port-scan primitive for an admin session. The allowance-by-provider-type item widens this from "an admin can store an unvalidated URL" to "an admin can *deliberately* point the AI layer at the instance-metadata service and have `resolve_task` POST completions there with the deployment's own network identity" — for exactly the two provider types the UI advertises as "any provider".
- **Cross-subsystem interactions:** the `explanation` assignment feeds `worker/llm_escalation.escalate_scan` (detection) and `app/explain.py` (API); the `agent_chat` assignment feeds `app/agent/engine.py` (excluded subsystem, same code path). `worker/celery_app.py:44` soft limit 420 s bounds the blast radius of a *hung* target but not of a fast one.

---

### [DEEPENED] AUDIT-4E-2 — The models.dev catalog fetch bypasses the SSRF policy on an unpinned client, **and the fetched data is trusted past its schema**
- **Original phase:** PROMPT-003 Audit Phase 4E
- **Severity:** **Critical** — Rule 12 + §6.4. The network half is unchanged; the *data*-trust half is new and is what the 4E entry explicitly deferred ("The models.dev catalog's data trust model … is a design question … not a defect found here"). Session A treats it as a defect because `fetch_live_catalog`'s own docstring is false.
- **Subsystem / file(s):** `backend/app/ai_catalog.py:36` (`CATALOG_URL`), `:144-158` `fetch_live_catalog`, `:86-126` `normalize_catalog`, `:161-206` `upsert_catalog`, `:209-234` `sync_catalog`; `backend/app/models.py` `ModelCatalogEntry`/`ModelCatalogProvider`; callers `app/ai_startup.py:32-40`, `worker/beat_tasks.py:393-405`.
- **Verification method:** hermetic probe + code-trace + direct column-type introspection.
- **Evidence — data trust:**
  - **`normalize_catalog` raises `AttributeError` on a hostile shape, and `fetch_live_catalog` does not catch it.** Docstring (`:145-146`): *"Fetch + normalize … or None on any failure (network, non-2xx, malformed). Never raises."* Measured:
    | payload | result |
    |---|---|
    | `{"providers": [1,2,3]}` | **raises `AttributeError: 'list' object has no attribute 'items'`** |
    | `{"providers": {"p": {"models": [{"name":"x"}]}}}` | **raises `AttributeError`** |
    | top-level list `[1,2,3]` | **raises `AttributeError: 'list' object has no attribute 'get'`** |
    | `{"providers": {"p": "not-a-dict"}}` | silently 0 providers / 0 models |
    | `{"providers": {"p": {"models": {"m": [1,2]}}}}` | providers=1, models=0 |
    | `{"providers": {}}` / `{"foo": 1}` | 0 / 0 |
    The `except` clause is `(httpx.HTTPError, json.JSONDecodeError, ValueError)` (`:153`) — `AttributeError` is not in it. Pinned by `test_fetch_live_catalog_raises_on_a_list_shaped_providers_key` (passes).
  - **No payload-size bound.** A 4 000-model / 5 000-char-name payload with `context: 10**12` and `cost: {input: 1e308, output: -5}` normalizes cleanly. Column types measured: `ModelCatalogEntry.context_window = INTEGER`, `max_output_tokens = INTEGER`, `model_id = VARCHAR(160)`, `cost_input/output = FLOAT`. Overflowing a 32-bit INTEGER on insert aborts the `upsert_catalog` transaction.
  - **Adversarial identifiers are copied verbatim.** `provider_id="evil/../../etc"`, `model_id="../../../etc/passwd"` → catalog id `evil/../../etc/../../../etc/passwd`, and `litellm_model_string()` (`ai_catalog.py:59-69`) concatenates them into the litellm model string handed to the Router. `display_name` accepts arbitrary text (`"; DROP TABLE model_catalog; --`) — safe from XSS (React escapes; no `|safe` in `frontend/src/components/ai-settings-card.tsx`), but unvalidated in storage.
- **Evidence — network half (unchanged from 4E):** `httpx.AsyncClient(timeout=20)` with no `transport=` and no `assert_url_allowed`; contrast `app/remediation.py:182-185`, `app/routers/imports.py`, `worker/probe.py` which all install `SSRFPinningTransport`.
- **Deeper analysis / honest impact scoping:** today the failure is *contained* — `ai_startup.bootstrap_catalog` (`:39`) and `beat_tasks.sync_model_catalog` (`:404`) both wrap in a broad `except Exception`, and `upsert_catalog`'s `delete`+`add_all`+`commit` are one transaction, so an overflowing hostile payload rolls back and `sync_catalog`'s "keeping existing catalog" ladder holds. The defect is therefore (a) a **false public contract** on `fetch_live_catalog`/`sync_catalog` that any future caller trusting it will crash on, and (b) **no size/schema/identifier validation at the trust boundary** of a third-party feed that drives the operator-facing provider picker. It is Critical by the mechanical Rule 12 rule, not because an attacker has a demonstrated data-corruption path today.
- **Cross-subsystem interactions:** the catalog is read by `settings.py:606-650` (`/api/settings/ai/catalog/providers|models`) and by `ai_config.resolve_tool_capability` (`:245-246`), so a hostile entry influences both the UI and the tool-calling gate. `worker/beat_tasks.py:76` refreshes every 12 h plus once per app start. Live DB today: 8 323 models / 225 providers.

---

### [NEW] AUDIT-SA5-1 — The locked `pyjwt==2.13.0` carries 10 published advisories; one is **live-reachable as an unauthenticated HTTP 500** through `app/security.py`
- **Severity:** **High** — §6.4 (a measured denial-of-service on the authentication path, plus unbounded persistent-log growth). Not Critical: no data exposure, no auth bypass, the process survives.
- **Subsystem / file(s):** `backend/pyproject.toml:66` (`pyjwt==2.13.0`, direct runtime pin); `backend/app/security.py:54-70` `decode_access_token`; `backend/app/deps.py:68-93`; `frontend/src/lib/api.ts`.
- **Verification method:** fresh `pip-audit` + in-process probe + **live read-only HTTP probe against `wardress-app-1` on :8321**.
- **Evidence — the advisory set** (`uv run --frozen pip-audit --skip-editable`, exit 1): `pyjwt 2.13.0` → `CVE-2026-102274, -101917, -102273, -102269, -102272, -102271, -102268, -102267, -102266, -102265`; fix `2.14.0` (released 2026-09-11).
  **Reachability triage, honestly, per advisory** — `app/security.py:23,62` uses a **single-algorithm HS256 allow-list with a symmetric secret**, which is the exact precondition every algorithm-confusion advisory requires:
  | advisory | class | reachable? |
  |---|---|---|
  | -102268 / -102271 / -102272 / -102273 | algorithm confusion (asymmetric key used as HMAC secret; DER / BOM / PEM-fold / container forms) | **No** — needs a mixed HS+asymmetric allow-list; Wardress is single-alg |
  | -102267 / -101917 / -102274 / -102266 | `PyJWKClient` / `PyJWKSet` paths | **No** — Wardress never uses `PyJWK`/`PyJWKClient` |
  | -102269 | permissive compact-JWS signature segment → revocation bypass | **No** — access tokens are stateless; refresh tokens are opaque random strings hashed in `models.RefreshToken`, never JWTs |
  | **-102265** | **`RecursionError` escapes `jwt.decode` on a deeply-nested compact-JWS header** | **YES — live-proven** |
- **Evidence — the reachable one:**
  - In-process: `decode_access_token` on a 26 681-byte token with a 20 000-deep nested header → **`RecursionError` escapes** the function's `except jwt.PyJWTError` (`:66`). Control: a plain bogus token returns `None` cleanly. Pinned by `test_decode_access_token_raises_recursionerror_on_a_nested_jwt_header` (passes).
  - **Live (read-only GET, one request per shape):**
    ```
    GET /api/health/live                                -> 200 {"status":"ok"}
    GET /api/sites  (bogus small bearer)                -> 401 {"detail":"Not authenticated"}
    GET /api/sites  (26681-byte nested-header bearer)   -> 500 Internal Server Error
    GET /api/sites  (266681-byte nested-header bearer)  -> 500 Internal Server Error
    docker logs wardress-app-1 | grep RecursionError
      RecursionError: maximum recursion depth exceeded while decoding a JSON array from a unicode string
    ```
  - Reachability mechanism: the shipped image runs `uvicorn` with **`httptools 0.8.0`** present (verified inside `wardress-app-1`), so uvicorn auto-selects the httptools parser whose default header cap is 80 KiB — a 27 KB `Authorization` header is accepted. `app/security.py:56`'s docstring **"Never raises — callers translate None into 401"** is therefore false on the default deployment.
  - Impact: one unauthenticated request per hit → HTTP 500 **plus a full traceback written to the container log**. Unbounded and repeatable ⇒ unbounded log growth on a self-hosted box. No data exposure, no auth bypass, worker survives.
- **Deeper analysis:** AUDIT-4E-4's method ("sweep the whole lockfile, not just the package that was reported") is what surfaced this — the 4E sweep found exactly 1 advisory because the PyJWT batch published on **2026-09-11**. This is the strongest single argument in this report for keeping a *scheduled* re-sweep rather than a one-shot gate.
- **Cross-subsystem interactions:** every authenticated route and every static-asset request in the SPA goes through this path (`deps.py:93`), so the auth path is the blast radius. A 500 is not a 401, so `frontend/src/lib/api.ts` does not attempt a silent refresh and surfaces the failure.

---

### [DEEPENED] AUDIT-4E-4 — The dependency gate went from **1 advisory to 12 across 3 packages**; `weasyprint` was not bumped
- **Original phase:** PROMPT-003 Audit Phase 4E
- **Severity:** **Critical** — unchanged in class (Rule 12 mechanical rule + §6.4 SSRF bullet); the *scope* is now three packages and eleven additional advisories.
- **Subsystem / file(s):** `backend/pyproject.toml:55` (`weasyprint==69.0`), `:66` (`pyjwt==2.13.0`); `backend/uv.lock`; `.github/workflows/ci.yml:60-66`; `backend/app/routers/reports.py:195-199` (sole WeasyPrint call site).
- **Verification method:** fresh `pip-audit` (exact CI command), JSON output parsed for per-advisory detail.
- **Evidence:** `cd backend; uv run --frozen pip-audit --skip-editable` → **exit 1**
  ```
  Found 12 known vulnerabilities in 3 packages
  oauthlib   3.3.1   CVE-2026-49265      fix 4.0.0
  pyjwt      2.13.0  CVE-2026-102274    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-101917    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-102273    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-102269    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-102272    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-102271    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-102268    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-102267    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-102266    fix 2.14.0
  pyjwt      2.13.0  CVE-2026-102265    fix 2.14.0
  weasyprint 69.0    PYSEC-2026-3940    fix 70.0

  Name  Skip Reason
  torch            Dependency not found on PyPI and could not be audited: torch (2.13.0+cpu)
  wardress-backend distribution marked as editable
  ```
  - `weasyprint 69.0` **not bumped** — still resolves 69.0 in the app image. AUDIT-4E-4's reachability caveat is unchanged and still holds (`HTML(string=html).write_pdf()` with no `stylesheets=`, `xmp_metadata=`, or `url_fetcher=`).
  - `oauthlib 3.3.1` CVE-2026-49265 is a **PKCE `code_challenge_method_plain` timing side-channel in the Authorization Code Grant**. Reverse-dependency chain measured from `uv.lock`: `oauthlib ← requests-oauthlib ← apprise` (a direct runtime pin). No `oauthlib` / `requests_oauthlib` import exists anywhere in the repo (repo-wide grep: zero hits). Apprise's OAuth2 support performs a token-endpoint fetch, not a PKCE Authorization Code Grant, so the vulnerable function is not reached. **It is, however, one of the reasons the CI gate is red.**
  - `pyjwt` — full per-advisory reachability triage in AUDIT-SA5-1, including the one live-proven path.
- **Deeper analysis:** 4E's framing ("a version pin was set once and never re-audited against the advisory feed") is confirmed and *quantified*: the advisory count for this exact lockfile went 1 → 12 in eleven days, all of it in a package the original audit never looked at. There is still no Dependabot/Renovate, and `ruff format --check` (AUDIT-4E-11) still masks the gate.
- **Cross-subsystem interactions:** `pyjwt` is the auth spine of the API **and** the worker (`celery_app` imports `app.settings`); `weasyprint` is only reachable from `app/routers/reports.py`.

---

### [DEEPENED] AUDIT-4E-10 — The frontend audit gate went from "2 moderate, exit 0" to **2 HIGH, exit 1**; and the deployed `walkthrough/` tree has **no audit gate at all**
- **Original phase:** PROMPT-003 Audit Phase 4E
- **Severity:** **High** — a documented CI gate (`ci.yml:143-144`) is now red, and §6.4's "docs/infra drift" is exceeded by a hard gate failure. The advisories are dev-tooling-only, which is why this is not Critical.
- **Subsystem / file(s):** `frontend/package.json:47` (`vitest ^4.1.10` → resolved 4.1.10); `frontend/pnpm-lock.yaml`; `.github/workflows/ci.yml:143-144`; `walkthrough/package.json`; `.github/workflows/static.yml:46-51`.
- **Verification method:** exact CI commands run fresh.
- **Evidence:**
  - `cd frontend; pnpm audit --audit-level high` → **exit 1**, `12 vulnerabilities found / Severity: 3 low | 7 moderate | 2 high`
    - **HIGH** `undici` DoS via unrequested WebSocket subprotocol (`GHSA-rfgv-xxqx-mfg5`), `<7.29.1`, path `. > vitest > jsdom > undici`
    - **HIGH** `undici` TLS certificate validation bypass via dropped connect options in `BalancedPool` (`GHSA-w293-vg96-wgc3`), `<7.29.1`, same path
    - MODERATE ×7 (5 × `undici`, 2 × `vitest`/`@vitest/mocker` path traversal `GHSA-82fw-gwwq-j7x9`, patch `>=4.1.11`)
    - LOW ×3 (all `undici`)
  - `cd walkthrough; pnpm audit --audit-level high` → **exit 1**, `8 vulnerabilities found / Severity: 1 low | 6 moderate | 1 high`
    - **HIGH** `nanoid` infinite loop when `size` is zero (`GHSA-2v37-7h3g-55p8`), `<3.3.18`, path `@tailwindcss/vite > vite > postcss > nanoid`
    - MODERATE ×6 (incl. `mermaid <11.16.1`, `GHSA-c4c3-pg64-4m4v`)
  - **`.github/workflows/static.yml` runs NO `pnpm audit`, no lint, no typecheck and no test for `walkthrough/`** — it only runs `pnpm install --frozen-lockfile` + `pnpm build` and then deploys. The high-severity `nanoid` advisory is therefore completely ungated on a tree published to GitHub Pages on every push to `main`.
- **Deeper analysis:** 4E recorded "two moderate, below the threshold" and graded it Low with the note that "no known advisories would be the wrong thing to record". Session A shows the threshold was crossed within days, and that a **second dependency tree with its own high advisory is outside the gate entirely** — 4E made the "two independent trees" observation in passing but it was never followed up with a gate.
- **Cross-subsystem interactions:** `frontend` ships inside `wardress-app:1` via `Dockerfile.app:7-13`; `walkthrough` is a separate GitHub Pages deployment. Neither is a runtime (production-dependency) advisory, so no data path is affected.

---

### [DEEPENED] AUDIT-4E-11 — The backend CI job cannot report at all: it now fails on the **first** command, so `ruff format --check`, `pip-audit`, `check_torch_osv` and `pytest` never execute
- **Original phase:** PROMPT-003 Audit Phase 4E
- **Severity:** **Medium** (unchanged class; the *magnitude* of the masking grew).
- **Subsystem / file(s):** `.github/workflows/ci.yml:56-72`; `backend/tools/run_stress_catalog.py`; `backend/tests/test_phase4_fresh_eyes_finding_repros.py:10`; `backend/tests/test_phase4c_api_surface_repros.py:18`.
- **Verification method:** fresh `ruff` runs at HEAD.
- **Evidence (HEAD baseline, measured at the start of this subagent's session):**
  - `uv run --frozen ruff check .` → **exit 1, `Found 9 errors.`** (was 0 at 4E time)
    - `I001` unsorted imports — `tests/test_phase4_fresh_eyes_finding_repros.py:10`
    - `F401` unused `uuid` — `tests/test_phase4c_api_surface_repros.py:18`
    - `S603`, `S110`, `ASYNC240`, `ASYNC230`, `E501` ×3 — all in `tools/run_stress_catalog.py:41,47,86,90,209,240,249`
  - `uv run --frozen ruff format --check .` → **exit 1, `24 files would be reformatted, 168 files already formatted`** (identical to 4E's count — unchanged)
  - Because `ci.yml:57-59` is a single `run: |` block, `ruff check .` aborting means **`ruff format --check`, `pip-audit`, `check_torch_osv.py` and the whole `pytest` suite never run.** The job is structurally incapable of reporting AUDIT-4E-4 or AUDIT-SA5-1.
  - **Honesty note:** later in the same session the counts rose to 26 files / 28 errors; every delta is a file added by *another concurrent subagent*. This subagent's own file appears in neither list.
- **Deeper analysis:** 4E attributed the failure to the *second* command. Session A shows the failure has migrated to the *first*, which means the proposed remedy ("split the lint into two steps") is necessary but no longer sufficient — the 7 `run_stress_catalog.py` errors are in a Phase-5A harness tool with no `per-file-ignores` entry in `pyproject.toml:70-104` (every other subprocess-shelling test file has one). A remediation prompt that only splits the CI step will still get a red job.
- **Cross-subsystem interactions:** the masked gates cover the auth spine (`pip-audit`), the heaviest dependency (`check_torch_osv`), and the entire backend test suite.

---

### [CONFIRMED] AUDIT-4E-3 — A hung provider stalls its caller for exactly one 30 s timeout *per key/deployment*, with no overall deadline
- **Original phase:** PROMPT-003 Audit Phase 4E
- **Severity:** **Medium** (unchanged) — bounded, recoverable, never silent on the scan row.
- **Subsystem / file(s):** `backend/app/llm.py:82,91,144-160,255-274`; `backend/worker/llm_escalation.py:59-78`; `backend/worker/celery_app.py:44-45` (soft 420 s / hard 480 s); `backend/app/ai_config.py:59` (`MAX_KEYS_PER_PROVIDER = 10`).
- **Verification method:** measurement, **6 passes** across two independent 3-pass runs (Rule 18), production `_REQUEST_TIMEOUT`/`_NUM_RETRIES` unchanged, local server that accepts and never answers.
- **Evidence:**
  | deployment count | run 1 | run 2 | variance | per-deployment |
  |---|---|---|---|---|
  | 1 key | 31.61 / 30.05 / 30.03 s | 31.39 / 30.03 / 30.08 s | ≤ 1.58 s | 30 s |
  | 2 keys | 60.97 / 60.06 / 60.09 s | — | ≤ 0.91 s | 30 s |
  - Keyless control still fast-fails: `InternalServerError: OpenAIException - Missing credentials...` (no network wait).
  - Arithmetic confirmed structurally: `_deployments` (`:144-160`) makes one litellm deployment per key, so the full 10-key pool = **~300 s** of wall clock inside one scan; with a fallback provider configured (`llm.py:263-265`) the bill is paid **twice** (~600 s) — past `celery_app`'s 420 s soft limit, i.e. a soft-time-limit kill rather than a graceful degradation.
  - Measurement validity: I re-ran after correcting the probe's `sys.path` insertion and explicitly asserted `app.llm.__file__` resolves inside the repo and that `_REQUEST_TIMEOUT=30, _NUM_RETRIES=2, _ALLOWED_FAILS=0, _COOLDOWN_SECONDS=60, MAX_KEYS_PER_PROVIDER=10`.
- **Deeper analysis:** 4E's `num_retries` arithmetic was already self-corrected in-phase; Session A adds the *interaction with the fallback group* and the precise distance to the soft limit. `worker/llm_escalation.py` and `app/explain.py:177` both `await` with no `asyncio.wait_for`, so there is no caller-owned deadline anywhere on the path.
- **Cross-subsystem interactions:** a 10-key hung pool turns a `changed`-verdict scan into a 420 s+ soft-limit kill; the row is then recovered by the 10-min stale sweep (`app/scanning.STALE_INFLIGHT`) — wasted work plus a failed-scan notification.

---

### [DEEPENED] AUDIT-4E-5 — Every runtime image is a floating tag; **and the worker's MiniLM weights are an unpinned floating model reference** whose pre-download failure is swallowed at build time
- **Original phase:** PROMPT-003 Audit Phase 4E
- **Severity:** **Medium** (unchanged class for the tags; the model-weight item is a distinct sub-finding graded Medium on its own).
- **Subsystem / file(s):** `docker-compose.yml:9,24,158`; `backend/Dockerfile.app:7,16`; `backend/Dockerfile.worker:8,9,26-27`.
- **Verification method:** code read + `docker inspect` on the live install.
- **Evidence (image layer, confirmed live):**
  | image | tag | digest |
  |---|---|---|
  | `wardress-db-1` | `postgres:16` | `postgres@sha256:1a6ab3f5…` (present, **not** in the compose file) |
  | `wardress-redis-1` | `redis:8-alpine` | `redis@sha256:38117873…` (present, not in compose) |
  | `wardress-app-1` | `wardress-app` (local build) | `sha256:edda300d…` |
  | `wardress-worker-1` | `wardress-worker` (local build) | `sha256:1540cb82…` |
  No `@sha256` appears in `docker-compose.yml` or either Dockerfile. Base images: `node:22-alpine`, `python:3.12-slim-trixie`, `mcr.microsoft.com/playwright/python:v1.61.0-noble`, plus the version-pinned `ghcr.io/astral-sh/uv:0.9.2` (the good pattern).
- **Evidence (NEW sub-finding — model weights):** `backend/Dockerfile.worker:27`
  ```
  RUN uv run --no-project python -c "from sentence_transformers import SentenceTransformer; \
      SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu')" \
      || echo "WARNING: MiniLM pre-download failed; layer 8 embeddings will degrade gracefully"
  ```
  - `SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')` resolves `main` — **no `revision=` pin, no commit SHA**. A repository compromise (or an upstream force-push) changes the weights baked into every `wardress-worker` image, and layer 8/9 embedding similarity would change silently — a *detection-accuracy* change with no code change and no signal in `capture_evidence`.
  - The `|| echo` makes a **failed pre-download a successful build**. The image ships without the model and layer 8/9 degrade — the exact "silent success" shape §6.4 treats critically, here for a build step. The `HF_HUB_OFFLINE=1` guard exists only in `backend/tools/build_fusion_dataset.py:51`, not in the image.
- **Deeper analysis:** 4E correctly noted the floating `ollama/ollama:latest` makes the "fully offline LLM" path non-reproducible. Session A adds a second floating reference that is strictly worse, because it is not a container tag an operator can see: it is a ~90 MB neural-network weight set whose change moves fused-risk scores with no git diff.
- **Cross-subsystem interactions:** layer 8 (`worker/detection/semantics.py`) and layer 9 fusion consume the embeddings; `worker/detection/training/fusion_model.json` is fitted against *specific* embeddings, so a weight change silently invalidates the fitted model.

---

### [CONFIRMED] AUDIT-4E-6 — The Ollama default endpoint is a Docker-only constant with a self-contradicting fallback chain
- **Severity:** **Low** (unchanged) — degrades visibly and safely.
- **Subsystem / file(s):** `backend/app/ai_ollama.py:28-33,40-46`; `backend/app/llm.py:128-141`; `backend/app/ai_migration.py:140-147`; `docker-compose.yml:155-162`; `.env.example:39-48`.
- **Verification method:** live read-only probe + code-trace.
- **Evidence (live, 2026-09-30):**
  ```
  docker exec wardress-app-1 python -c "import socket; socket.getaddrinfo('ollama',11434)"
    -> FAILED: gaierror [Errno -2] Name or service not known
  SELECT label, provider_type, base_url, enabled, validation_status, credentials_encrypted FROM ai_providers;
    -> "Ollama (local)" | ollama | http://ollama:11434 | t | unknown | (null)
  SELECT task, provider_id, model_id FROM ai_task_assignments;  -> 0 rows
  ```
  The `ollama` profile container is not running, the hostname does not resolve, the provider is nonetheless `enabled = t`, and with zero assignments the escalation correctly returns "not configured". Degradation is safe; the drift is real. The self-contradiction also persists in code: `normalize_base(None)` and `normalize_base("")` → `http://ollama:11434` (Docker-only) while `normalize_base("   ")` → `http://localhost:11434`; the module comment at `:28-32` claims "a bare host install uses localhost". Three copies of the rule exist (`ai_ollama.normalize_base`, `llm._litellm_api_base:140`, `ai_migration` seed).
- **Cross-subsystem interactions:** a fresh install is "AI on by default" against an endpoint that cannot resolve, so the operator's first Settings→AI experience is a 422 "Could not resolve host".

---

### [CONFIRMED] AUDIT-4E-7 — The Ollama model-pull stream has no deadline of any kind
- **Severity:** **Low** (unchanged).
- **Subsystem / file(s):** `backend/app/ai_ollama.py:25-26,114-139` (`_PULL_TIMEOUT = None`; `httpx.AsyncClient(timeout=None)`); `backend/app/routers/settings.py:855-915` (SSE, `enforce_user_rate_limit` at `:870`).
- **Verification method:** code-trace (live reproduction impossible: the `ollama` profile container is intentionally not running).
- **Evidence:** `pull_stream` builds `httpx.AsyncClient(timeout=_PULL_TIMEOUT)` with `_PULL_TIMEOUT = None`; the SSE generator at `settings.py:907-913` has no `asyncio.wait_for` and no idle-progress watchdog; the two sibling discovery calls pin `_DISCOVERY_TIMEOUT == 15`. The endpoint *is* SSRF-validated (`settings.py:891`) and rate-limited (2 tokens, `:870`), so the only gap is liveness.
- **Deeper analysis:** the endpoint's `body.base_url` fallback at `settings.py:872,885` means a request **without** `provider_id` is validated against a caller-supplied `base_url` — so an admin can aim a never-ending SSE stream at any host `assert_url_allowed` permits, with the connection held for the life of the response.

---

### [DEEPENED] AUDIT-4E-8 — The heuristic redactor's leak reaches a **Viewer** through the layer-8 evidence and an **HTTP 503 body**; the original finding named only logs + `validation_detail`
- **Original phase:** PROMPT-003 Audit Phase 4E
- **Severity:** **High** (upgraded from Medium) — §6.4's "a documented spec requirement simply not met" plus a privilege/credential-exposure crossing: the leaked value is an **admin-configured provider API key** and the reader is any authenticated role.
- **Subsystem / file(s):**
  - redactor: `backend/app/llm.py:60-79` (`_SECRET_PATTERNS`, `_scrub_secrets`)
  - sinks: `backend/app/llm.py:199-202` (`_acompletion` log + `LLMUnavailable` message), `backend/app/llm.py:389-390` (`validate_provider_call` detail)
  - **new sinks found:** `backend/worker/llm_escalation.py:72-75` → `{"status": f"unavailable: {exc}"}`; `backend/app/explain.py:179` → `ExplainError` → `backend/app/routers/sites.py:449-450` → `HTTPException(503, str(exc))`
  - readers: `backend/app/routers/settings.py:760` (persists `validation_detail[:500]`, returned in `AiProviderOut`); `backend/app/routers/sites.py:396-399` `get_scan` uses **`CurrentUser`** (any role incl. Viewer) and `backend/app/schemas.py:161-172` `ScanFindingOut.evidence: dict | None` is part of the response.
- **Verification method:** hermetic probe driving the **production** `validate_provider_call` and `ResolvedTask.generate` against a local fake OpenAI-compatible endpoint returning `401 {"error":{"message":"Incorrect API key provided: <key>"}}` — the exact real-world shape.
- **Evidence (leak constructed end-to-end, key = `shorty123`, 9 chars):**
  1. **Persisted DB column:** `validate_provider_call` returned
     `detail = 'AuthenticationError: litellm.AuthenticationError: AuthenticationError: OpenAIException - Incorrect API key provided: shorty123. You can find your API key at .... Received Model Grou'`
     → `settings.py:760` stores this in `ai_providers.validation_detail`. **short key present: True.**
  2. **`LLMUnavailable` message:** `'AuthenticationError: ... Incorrect API key provided: shorty123. You can find '` → **present: True.** This string becomes:
     - `llm_escalation.escalate_scan` → `{"status": "unavailable: …shorty123…"}` → persisted as the **layer-8 `ScanFinding.evidence`** on the scan row → returned by `GET /api/sites/{id}/scans/{scan_id}` to a **Viewer**.
     - `explain.explain_scan` → `ExplainError` → **HTTP 503 body** to the caller.
  3. **Logs:** 5 log records contained the key (one from `llm.py:201`, four from litellm's own DEBUG exception logging).
  4. **Control (proves the redactor is the only thing that would have saved it):** `_scrub_secrets("key=shorty123")` → `'key=shorty123'` (unchanged); `_scrub_secrets("key=sk-live-ZZZZ…40")` → `'key=[REDACTED]'`.
  Pinned by `test_escalation_evidence_carries_the_unredacted_short_key` (passes).
- **Deeper analysis:** 4E's own scoping ("it leaks nothing the admin cannot already read") is what Session A overturns. The evidence is a function of *the failing provider*, not of the requesting user, and the scan-detail endpoint is `CurrentUser`, so the leak crosses the RBAC boundary Phase 4C established. The precondition is unchanged and narrow (a custom `openai_compatible` endpoint, or an unusually short vendor key) — but the *consequence* is larger than recorded.
- **Cross-subsystem interactions:** detection (layer-8 evidence) → API (`/api/sites/…/scans/…`) → frontend (`scan-detail.tsx` renders finding evidence) is the full path a leaked credential travels; the AI settings card shows `validation_detail` to admins.

---

### [CONFIRMED] AUDIT-4E-9 — Dependency-hygiene residue (`aiosqlite`, runtime `scikit-learn`)
- **Severity:** **Low** (unchanged).
- **Subsystem / file(s):** `backend/pyproject.toml:35` (`scikit-learn==1.9.0` in `[project] dependencies`), `:70` (`aiosqlite==0.22.1` in the dev group); `backend/tools/refit_fusion_model.py:46,367,445`.
- **Verification method:** repo-wide grep.
- **Evidence:** `aiosqlite` — zero imports anywhere in `backend/` (only a `models.py:11` comment and `tests/test_phase41_docs_sync.py:51` asserting its absence from docs). `sklearn` — only `tools/refit_fusion_model.py`. Both images install the runtime table (`Dockerfile.app:28,33`, `Dockerfile.worker:20,32` with `--no-dev`), so `scikit-learn` ships in `wardress-app:1` and `wardress-worker-1` although nothing at runtime imports it.
- **Deeper analysis:** `scikit-learn` also pulls `scipy` and a large numeric stack into the *app* image (which has no use for embeddings or model fitting). That is the concrete cost of the misclassification.

---

### [NEW] AUDIT-SA5-2 — `litellm` logs the **full LLM prompt and the full raw response** in plaintext at DEBUG; `app/llm.py` sets three litellm globals but never `turn_off_message_logging`
- **Severity:** **Low** as shipped — **measured**, not asserted: `docker logs wardress-app-1 | grep -c LiteLLM` = **0**, `docker logs wardress-worker-1 | grep -c LiteLLM` = **0**; the app and worker configure **no** logging at all (`app/main.py` has no `basicConfig`/`setLevel`; there is no `LOG_LEVEL` env anywhere in the repo), so the default effective level drops these records, and litellm's `LoggingWorker` created no file in the process CWD in my run.
- **Subsystem / file(s):** `backend/app/llm.py:54-58` (the three globals that *are* set); installed `litellm` (`litellm_logging.py:1100` prints a full `curl` reproduction; `:1161` prints `RAW RESPONSE`); `litellm.turn_off_message_logging` default.
- **Verification method:** hermetic probe driving the **production** `app.llm._build_router(...).acompletion(...)` against a local fake endpoint with a root logger set to DEBUG, then re-measuring against the live containers.
- **Evidence:**
  - Globals after importing `app.llm`: `drop_params=True`, `telemetry=False`, `suppress_debug_info=True`, **`turn_off_message_logging=False`**, `log_level='DEBUG'`, `json_logs=False`, `store_audit_logs=False`, `success_callback=[]`, `failure_callback=[]`, `callbacks=[]`.
  - 96 log records captured; **3 contained the full prompt** (including the injected `PROMPT-SENTINEL`, which stands in for the ≤2 000 chars of *monitored-site text* that `build_classification_prompt:429` puts in the prompt) and **2 contained the full raw response**. The `litellm_logging.py:1100` record is literally:
    ```
    POST Request Sent from LiteLLM:
    curl -X POST \
    http://127.0.0.1:33094/v1/ \
    -H 'Authorization: Be****YZ' \
    -d '{'model': 'fake-model', 'messages': [{'role': 'user', 'content': 'PROMPT-SENTINEL-9f3a1c-do-not-log-me'}], ...}'
    ```
  - **Credit where due:** litellm redacts the credential in its own logs (`api_key → 'REDACTED'`, `Authorization: Be****YZ`) — **0 records contained the API key.**
  - Files created in the process CWD: **none** (no `litellm_log.json`, no `litellm.db`).
  - litellm's own egress: its cost map is loaded from the package (4 436 entries, **no network fetch**), and `LITELLM_LOG_MODE` / `LITELLM_TELEMETRY` are unset. No hidden phone-home at import.
- **Deeper analysis:** the leak is gated behind a debug flag, so Low *today*. It matters because (a) raising a log level is the most common debugging action, (b) the leaked content is **attacker-influenced** (text captured from a monitored site) and lands in whatever sink the operator points at — including a shared SIEM, (c) it bypasses `llm.py`'s own stated discipline ("scrub before writing [to] persistent logs / SIEM / support tickets", `:60-64`) entirely, and (d) the one-line remedy sits right next to the three globals that already exist.
- **Cross-subsystem interactions:** the worker runs the escalation prompt (worker logs are the sink); the app runs the explain prompt.

---

### [NEW] AUDIT-SA5-3 — There is **no Fernet key ring, version prefix, or re-encrypt path**: rotating `CREDENTIALS_ENCRYPTION_KEY` silently destroys every stored credential, and the AI layer degrades to **unauthenticated** requests
- **Severity:** **Medium** — §6.4 "a partial implementation that degrades gracefully but doesn't meet the original intent", with an unrecoverable-data-loss consequence. Not High: the trigger is operator-initiated and there is no attacker path.
- **Subsystem / file(s):** `backend/app/crypto.py` (whole file, 61 lines); callers `backend/app/llm.py:108-125` `provider_api_keys`, `backend/app/ai_config.py:73-82` `_keys_unreadable`, `:85-100` `provider_out`, `backend/app/remediation.py:204-208` `decrypt_hook_url`, `backend/app/settings_store.py:33-42` `load_setting`, `backend/worker/alert_tasks.py:63-68` `_channel_config`.
- **Verification method:** in-process probe (encrypt under key A, clear both lru_caches, swap to key B, exercise every decrypt caller).
- **Evidence:**
  - `crypto` exports exactly: `DecryptionError, Fernet, InvalidToken, _fernet, base64, decrypt_json, decrypt_text, encrypt_json, encrypt_text, get_settings, hashlib, json, lru_cache`. **No key ring, no `v1:`-style prefix, no re-encrypt helper.** A repo-wide grep for `reencrypt|rotate|keyring|key_ring|old_key|previous_key|FERNET_KEYS` over `backend/app`, `backend/worker`, `backend/alembic`, `scripts` returns **zero** rotation-related hits.
  - After the swap: `decrypt_json` → `DecryptionError`. Then, per caller:
    | caller | observable result |
    |---|---|
    | `provider_api_keys` | `[]` + one `logger.warning("AI provider %s credentials undecryptable — treating as keyless")` per call |
    | `_keys_unreadable` / `provider_out` | `True` (the UI *does* show a re-save prompt — the one real signal) |
    | **`_deployments`** | **builds a deployment with NO `api_key` and NO `rpm`** — measured `params keys: ['model','timeout']` — i.e. an authenticated hosted provider silently becomes an **anonymous** request against whatever `base_url` is stored |
    | `decrypt_hook_url` | `None` → `_fire` writes `failed` / "webhook URL could not be decrypted — re-save the hook" (visible) |
    | `load_setting` | `None` + `logger.warning("Settings row %r could not be decrypted (rotated key?) - treating as unconfigured")` → **SMTP and Telegram settings silently become unconfigured**, so every alert fails with "SMTP is not configured" / "bot token is not configured" |
  - **Undocumented:** `.env.example` (95 lines) and `docs/**` contain **zero** occurrences of `CREDENTIALS_ENCRYPTION_KEY` rotation consequences (a grep for `rotat` across `docs/` + `README.md` returns only refresh-token and UA-rotation hits). `scripts/diagnostics.ps1:42` reports the key's *presence* but says nothing about rotation.
  - **One positive:** `scripts/update.ps1` does **not** regenerate secrets (zero matches for `CHANGE_ME`, `CREDENTIALS_ENCRYPTION_KEY`, `JWT_SECRET`, `POSTGRES_PASSWORD` in that file), so a routine upgrade does not trigger this.
  - Pinned by `test_crypto_has_no_key_ring_and_rotation_downgrades_to_keyless` (passes).
- **Deeper analysis:** the sharpest edge is not the loss, it is the **direction of the degradation**: an authenticated custom `openai_compatible` provider (a private model gateway, say) becomes an *anonymous* one, so requests keep flowing to a stored `base_url` with no credential — which, combined with AUDIT-4E-1 (no use-time validation), means a key rotation can silently turn a validated provider into an unvalidated, unauthenticated outbound call. Second edge: `resolve_tool_capability` passes `keys[0] if keys else None` → `None` after rotation → the Ollama `/api/show` probe fails → returns `None` ("unknown") → the **agent-chat tool-capability gate silently stops gating**, letting a non-tool model back the agent.
- **Cross-subsystem interactions:** AI (`ai_providers`) · delivery (`app_settings` SMTP/Telegram, `notification_channels`, `remediation_hooks`) — every one of those subsystems is keyed on the same single Fernet key, so one env change silently disables alerting **and** AI together.

---

### [NEW] AUDIT-SA5-4 — CI never builds either Dockerfile, and the deployed `walkthrough/` tree has no audit, lint, typecheck or test gate
- **Severity:** **Medium** — §6.4 "a documented spec requirement simply not met / infra gap". The two Dockerfiles are the entire production delivery path and have **zero** CI coverage.
- **Subsystem / file(s):** `.github/workflows/ci.yml:154-165` (the `docker` job); `.github/workflows/static.yml:37-51`; `backend/Dockerfile.app`; `backend/Dockerfile.worker`.
- **Verification method:** code read of both workflows.
- **Evidence:**
  - `ci.yml`'s `docker` job has exactly two steps: `actions/checkout` and `docker compose config --quiet`. **No `docker build`.** So `Dockerfile.app` (55 lines: a Node frontend build stage, a `uv sync` dependency layer, a premailer/WeasyPrint apt layer) and `Dockerfile.worker` (36 lines, incl. a network download of neural-network weights) are never built anywhere in CI. A broken Dockerfile, a drifted corepack/pnpm version, or a failed MiniLM pre-download is discovered only by the operator running `scripts/update.ps1` — and `Dockerfile.worker:27`'s `|| echo` means the *last* of those cannot fail the build at all (AUDIT-4E-5).
  - `static.yml` builds and **publishes** `walkthrough/` with `pnpm install --frozen-lockfile` + `pnpm build` and no `pnpm audit`, no lint, no `tsc -b`, no tests. It currently carries a **HIGH** advisory (`nanoid`, `GHSA-2v37-7h3g-55p8`) — AUDIT-4E-10.
  - `ci.yml` has no `docker/build-push-action`, no image scan (Trivy/Grype), no SBOM, and no layer check. `.github/dependabot.yml` does not exist.
- **Deeper analysis:** AUDIT-4E-5's "no Renovate/SHA-bump automation" note and this compose to one structural gap: **the project's only production artifact is built and shipped entirely outside CI.** The frontend job *does* build (`ci.yml:152`) and the backend job *does* test, but the thing the operator actually runs — `docker compose up` — has no gate at all. Note also `Dockerfile.app:9` runs `corepack enable` with no pnpm version and `frontend/package.json` sets no `packageManager` field, so the app image can build with a **different pnpm major** than CI's pinned 11.13.1 (`ci.yml:133-135`).
- **Cross-subsystem interactions:** a `pnpm`/`uv`/Node bump that breaks `Dockerfile.app:9` reaches production unblocked.

---

### [NEW] AUDIT-SA5-5 — `.dockerignore` excludes git-tracked ignores, so local scratch logs are baked into the shipped `wardress-app` image
- **Severity:** **Low** — proven instance, small payload today; the *class* is a secret-leak channel into a published image.
- **Subsystem / file(s):** `.dockerignore` (root, 15 lines); `backend/Dockerfile.app:31` (`COPY backend/ .`).
- **Verification method:** local file listing + `docker exec` on the live app container.
- **Evidence:**
  - `.dockerignore` lists `.git/`, `reference/`, `docs-cache/`, `frontend/node_modules/`, `frontend/dist/`, `backend/.venv/`, `**/__pycache__/`, `**/.pytest_cache/`, `**/.ruff_cache/`, `landing-page`, `.env`, `uuuu`, `*.md`, `!backend/README.md`, `EXample`. It is **allowlist-by-omission** for everything else.
  - `git status --ignored backend/` lists `backend/build_app.log` and `backend/build_app.err.log` as **gitignored** local files (dated 2026-08-25).
  - Both are present in the running image: `docker exec wardress-app-1 ls -la /app` shows `build_app.err.log` (56 B) and `build_app.log` (0 B).
  - Content of today's instance: `ERROR: failed to solve: app: copy /app/dist: not found` — harmless.
  - The image also contains `/app/.scratch_captures/`, `/app/Dockerfile.app` and `/app/Dockerfile.worker` (the build context copies the whole backend directory, Dockerfiles included).
- **Deeper analysis:** any local `*.log`, `*.json`, `*.sqlite`, editor backup or tooling cache under `backend/` or `frontend/` lands in a production image, because `.dockerignore` does not exclude gitignored files generically. On a developer machine that has ever run the suite against a real `.env`, or a test that wrote credentials to a log, that content is in the image layer forever. The images are local builds (not pushed to a registry today), which caps the exposure — but they are also what a user would push to a private registry to deploy elsewhere.
- **Cross-subsystem interactions:** none at runtime; purely a build-hygiene defect.

---

### [NEW] AUDIT-SA5-6 — Both runtime images run as **root**, and the compose services set no `security_opt`, `cap_drop`, `read_only` or `user`
- **Severity:** **Low** — attack-surface reduction, no demonstrated exploit. Phase 10 may weigh this as Medium; the honest position is that it is a hardening gap, not a boundary weakness.
- **Subsystem / file(s):** `backend/Dockerfile.app:16` (`python:3.12-slim-trixie`, no `USER`), `backend/Dockerfile.worker:8` (`mcr.microsoft.com/playwright/python:v1.61.0-noble`, no `USER`); `docker-compose.yml` (no `user:`, `security_opt:`, `cap_drop:`, `read_only:` on any service).
- **Verification method:** Dockerfile read + `docker exec … id` on the live containers.
- **Evidence:** no `USER` directive in either Dockerfile; the `/app` listing shows every file root-owned. `uv`/`uvx` remain in `/bin` in the final images (`Dockerfile.app:17`, `Dockerfile.worker:9`) — the official Astral pattern, noted for completeness rather than as a defect. No `curl`/`wget` debug leftovers; the only `curl` is the compose healthcheck's, which is legitimate (`docker-compose.yml:84`).
- **Deeper analysis:** the worker executes attacker-influenced page JavaScript in a Playwright browser and writes to a shared named volume (`scan-artifacts`, mounted `:ro` in the app, `rw` in the worker). Root in the worker + a browser RCE primitive is the classic container-escape setup. The artifact volume is created root-owned, so simply adding `USER` needs a matching ownership fix — which is exactly why this is a deliberate, scoped hardening task rather than a one-liner.

---

### [NEW] AUDIT-SA5-7 — `LOGIN_RATE_LIMIT_PER_IP` is read by the code, exercised by tests, and documented in **neither** `.env.example` **nor** `docker-compose.yml`
- **Severity:** **Low** — §6.4 "docs/infra drift". The code default (30) is safe; the operator simply cannot tune the tightest security knob in the system.
- **Subsystem / file(s):** `backend/app/config.py:86` (`login_rate_limit_per_ip: int = 30`); `backend/app/ratelimit.py`; `.env.example:53-59`; `docker-compose.yml` (app service env block).
- **Verification method:** exhaustive env-var cross-reference (full table in §5 below).
- **Evidence:** `app/config.py` declares 20 settings; `.env.example` documents 14 of them; `docker-compose.yml` forwards 13 into the app container. The single gap: `LOGIN_RATE_LIMIT_PER_IP` is **read** (config + ratelimit), **set in tests** (`tests/conftest.py:33`, `tests/test_phase17_auth_audit.py:211,226`), **absent from `.env.example`** and **absent from compose**, so it is permanently pinned at the code default 30. (The one other asymmetry, `ARTIFACTS_DIR`, is a *deliberate, correctly-documented* exclusion — see the table.)
- **Cross-subsystem interactions:** `POST /api/auth/login` is the credential-stuffing surface; the general per-IP budget (300/60 s) plus this one (30/60 s) are the two walls.

---

### [NEW] AUDIT-SA5-8 — `actions/checkout` leaves `persist-credentials` at its default in all three workflows
- **Severity:** **Low** — the exposed token is `permissions: contents: read` and ephemeral, so the impact is repository-clone read access that a fork PR author already has.
- **Subsystem / file(s):** `.github/workflows/ci.yml:47,103,132,158`; `.github/workflows/static.yml:35`.
- **Verification method:** workflow read + token-context grep.
- **Evidence and the questions asked, answered precisely:**
  - **Can a PR exfiltrate secrets?** **No CI secrets exist.** `grep 'secrets\.'` over both workflows returns **zero** hits. `ci.yml` uses job-scoped literal placeholders (`POSTGRES_PASSWORD: wardress-test`, `JWT_SECRET: ci-placeholder-not-a-real-secret`, `CREDENTIALS_ENCRYPTION_KEY: ci-placeholder-encryption-key`), all against throwaway service containers; the `docker` job's placeholders exist only so `docker compose config --quiet` can expand `${VAR:?}` and **no container is started**.
  - **Are there `pull_request_target` triggers?** **No.** `ci.yml` triggers on `push: [main]`, `pull_request`, `workflow_dispatch`; `static.yml` on `push: [main]` and `workflow_dispatch` — so a fork PR cannot reach the Pages job at all.
  - **Can a fork PR run anything with write scope?** **No.** Top-level `permissions: contents: read` in `ci.yml`; `static.yml` grants `pages: write` + `id-token: write` but only on `push` to `main`.
  - **Are caches poisoned across branches?** **Not meaningfully.** `astral-sh/setup-uv` (`cache-dependency-glob: backend/uv.lock`), `actions/setup-node` (`cache-dependency-path: frontend/pnpm-lock.yaml`) and `static.yml`'s walkthrough cache are all **content-hash-keyed on the lockfile**; GitHub cache scoping also prevents a fork's cache from being read by the base branch.
  - **Is `persist-credentials` left on?** **Yes** — never set to `false` in any of the 5 checkout steps, so the `GITHUB_TOKEN` is written into `.git/config` as an `http.https://github.com/.extraheader` and is therefore readable by any process the job runs. For `ci.yml`'s `backend` job that includes `uv run pytest` — i.e. **a fork PR's own test code executes with the token in its git config.** The token is read-only, so the practical gain is low, but the one-line hardening is standard and free.
  - **Verified-clean, preserved from 4E:** all actions SHA-pinned with version comments (`actions/checkout@fbc6f399…` v5, `astral-sh/setup-uv@11f9893b…`, `pnpm/action-setup@0977fd99…`, `actions/setup-node@a0853c24…`); `permissions: contents: read`; per-ref `concurrency` never cancelling `main`; `uv` 0.9.2 consistent across CI and both Dockerfiles; pnpm 11.13.1 consistent between `ci.yml:135` and `walkthrough/package.json`.

---

## 2. Alert-delivery findings (Phase 4D re-verification)

### [DEEPENED] AUDIT-4D-1 — Mid-delivery orphaning is now **deterministically reachable from a user-controlled field** (a CR/LF in a site name), and the real window is 40 s × (channels − 1)
- **Severity:** **High** (unchanged class; the *reachability* is new and worse than "a crash").
- **Subsystem / file(s):** `backend/worker/alert_tasks.py:77-81` (any-row guard), `:125-166` (per-channel loop + per-channel commit), `:179-188` (wrapper → `"error"`); `backend/worker/beat_tasks.py:327-376` (`_resweep_undelivered`, zero-rows predicate); `backend/app/alerting.py:32` (`SEND_TIMEOUT_SECONDS = 20`), `:133-139` (message construction **outside** the `try`), `:200-203` (Apprise wait-for = 40 s), `:217-252` `deliver_to_channel`.
- **Verification method:** hermetic probe driving the production `build_alert_content` + `EmailMessage` with a hostile `site_name`; code-trace for the propagation.
- **Evidence:**
  - **Window width (from the timeout constants, not asserted):** per-channel wall clock before a commit can fail is up to **20 s** (SMTP, `alerting.py:32,146`) or **40 s** (Apprise, `alerting.py:200-203`). With *N* channels the vulnerable window is up to **40 × (N − 1) s**; the guard (`:77-81`) and the resweep predicate (`beat_tasks.py:340-350`) meet nowhere in that interval, exactly as 4D stated. Channels are ordered by `created_at` (`:98`), so global channels created first are the ones that survive.
  - **NEW reachability — the orphan is now triggerable by data, not only by a crash.** Probe with `site_name = 'acme\r\nBcc: attacker@evil.example'`:
    ```
    EmailMessage construction RAISED ValueError: Header values may not contain linefeed or carriage return characters
    ```
    The raise happens at `alerting.py:135` (`message["Subject"] = content.email_subject`), i.e. **before** `send_email`'s `try:` at `:158`, so it propagates out of `send_email` → out of `deliver_to_channel` (documented "Routes one rendered alert to one channel config", `alerting.py:217`, contract "Returns (ok, detail)") → into `_deliver_alert`'s channel loop at `alert_tasks.py:146` → the task wrapper at `:186-188` returns `"error"`. Result: **no delivery row for that channel or any later channel, and the resweep's zero-rows predicate will never re-arm it.** Pinned by `test_deliver_to_channel_raises_on_a_crlf_site_name` (passes).
  - **Why the input is reachable:** `backend/app/schemas.py:50-65` `SiteCreate.name` is `Field(min_length=1, max_length=200)` with `strip_name` doing only `v.strip()` — which removes *leading/trailing* whitespace, not interior CRLF. `POST /api/sites` requires `AnalystUser` (`app/routers/sites.py:111-114`).
  - **Positive control (the same probe, the other half of the question):** the HTML **body** is safe. `site_name = '<img src=x onerror=alert(1)>"><script>alert(2)</script>'` → `raw <script> in html: False`, `raw <img in html: False`, `escaped &lt; in html: True`. Jinja autoescape is on (`alerting.py:36-39`, `select_autoescape(["html"])`), there is **no `|safe` anywhere** in the three templates, and `premailer.transform` (`:98`) preserves the escaping. **No HTML injection and no SMTP header injection** — `Bcc injected into wire format: False` in every case, because `EmailMessage` refuses the header outright. Pinned by `test_alert_html_template_escapes_hostile_site_names` (passes).
- **Deeper analysis:** 4D sized the finding on "a worker crash or a DB hiccup on any per-channel commit". Session A's addition is that the *same permanent, silent* state is reachable from a field any Analyst can set, with **no crash at all** — which moves the probability term from "rare" to "1.0 for any site whose name ever contains a CR or LF". The remaining defense-in-depth gap is that `deliver_to_channel`'s documented never-raise contract is not implemented: wrapping the message construction in the same `try` (or sanitising the subject) would convert a permanent alert-delivery failure into one `failed` delivery row the dashboard shows.
- **Cross-subsystem interactions:** detection (`scan_tasks` → `Alert`) → delivery (worker) → API (`/api/alerts`, `alerts.tsx`). Per AUDIT-4B-1 the same "silent, no row" shape applies to the alert row itself.

---

### [CONFIRMED] AUDIT-4D-2 — The delivery idempotence guard is check-then-act
- **Severity:** **Medium** (unchanged).
- **Subsystem / file(s):** `backend/worker/alert_tasks.py:77-81` (plain `SELECT … LIMIT 1`) vs `backend/worker/remediation_tasks.py:56-70` (the conditional-UPDATE claim this same codebase uses for exactly this hazard).
- **Verification method:** code-trace + the existing committed repro re-run in this session's regression batch.
- **Evidence:** the guard is a bare `db.scalar(select(AlertDelivery).where(alert_id == …).limit(1))` with no arbitration between check and the first `:166` commit; two sessions can both observe zero rows. **Production reachability, answered concretely:** yes, but the window is narrow and specific — `_resweep_undelivered` re-enqueues an alert with zero delivery rows every `REDELIVERY_SWEEP_SECONDS = 300 s` (`beat_tasks.py:69`) for alerts older than `REDELIVERY_GRACE = 5 min` (`:70`). So a delivery that has been in flight for > 5 min (e.g. blocked behind a worker pool exhausted by the 20–40 s per-channel timeouts, or on a retry after a worker restart) **will** be re-enqueued while the original is still running, and both proceed past the guard. Harm is duplicate operator notifications, not corruption.
- **Cross-subsystem interactions:** the 5-min resweep cadence multiplies with the per-channel timeout budget from AUDIT-4D-1.

---

### [CONFIRMED] AUDIT-4D-3 — The favicon resolver builds an **unpinned** httpx client
- **Severity:** **Medium** (unchanged).
- **Subsystem / file(s):** `backend/app/site_icons.py:193-195` (`httpx.AsyncClient(timeout=…, follow_redirects=False)` — no `transport=`), `:111-118` `_gate_url` (calls the **blocking** `assert_url_allowed` directly on the event loop, unlike `probe.py`/`remediation.py`), `:133-134` (gate, then `client.get` — the check-vs-connect window).
- **Verification method:** live hermetic probe that records the constructed client's kwargs, plus a hop-by-hop redirect matrix.
- **Evidence:**
  ```
  kwargs the favicon resolver's client was built with: [['follow_redirects', 'timeout']]
  contains 'transport' (SSRFPinningTransport)?           False
  ```
  Contrast `app/remediation.py:182-185` (`transport=SSRFPinningTransport(allow_private_networks=…)`) and `app/ssrf_transport.py`.
- **Deeper analysis — the redirect gate re-probed hop by hop** (first hop allowed so the redirect *target* is under test):
  | redirect target | result |
  |---|---|
  | `http://169.254.169.254/latest/meta-data/` | `ConnectTimeout` — **not** `SSRFBlockedError` (link-local is not blocked under the opt-in; see AUDIT-4E-1's table) |
  | `http://10.0.0.5:8080/internal` | `ConnectTimeout` (RFC1918, allowed by the opt-in — intended) |
  | `file:///etc/passwd` | refused at the scheme check (`:140-142`) |
  | `gopher://127.0.0.1:11211/_stats` | refused at the scheme check |
  | 302 with no `Location` | `None` |
  | self-redirect loop | capped at 3 hops (4 requests observed) |
  | `http://user:pass@127.0.0.1:1/x`, `//127.0.0.1:1/x`, `http://[::1]:1/x` | refused at hop 0 under the default policy (`Address 127.0.0.1 is in a blocked range`) |
  **Verdict: redirect-to-internal IS closed** for the http/https + credential + loopback classes 4D tested, and the scheme check and hop cap are real. The two residual gaps are exactly the two 4D named: no DNS pinning, and the event-loop-blocking `getaddrinfo` per hop.
- **Cross-subsystem interactions:** the per-site `allow_private_networks` flag is the opt-in that opens the link-local case; the feature is default-OFF (`site_icons.get_favicon_enabled` + `settings.py:921-939`).

---

### [DEEPENED] AUDIT-4D-4 — The "size-capped so a hostile server cannot exhaust memory" claim is not delivered — **measured at 64.2 MiB of Python heap for a 32 MiB body**
- **Severity:** **Medium** (unchanged) — a partial implementation that does not meet its stated intent.
- **Subsystem / file(s):** `backend/app/site_icons.py:21-22` (the docstring claim), `:151` (`body = resp.content[: max_bytes + 1]`), `:60-61` (`_MAX_ICON_BYTES = 64 KiB`, `_MAX_HOME_HTML_BYTES = 256 KiB`).
- **Verification method:** measurement with `tracemalloc` around a real 32 MiB fetch through the production `_fetch_with_gates`.
- **Evidence:**
  ```
  /bomb served 32 MiB with _MAX_ICON_BYTES=65536
  result: ALLOWED  body=65537B  ctype='image/png'
  python-traced peak during the fetch: 64.2 MiB (baseline 0.0 MiB)
  ```
  The 32 MiB body is fully materialised (≈32 MiB in the httpx response) and then copied by the slice (another ≈32 MiB) — hence 2×. `client.get(url)` at `:134` reads the entire body before returning; the cap applies afterwards. Session A's contribution over 4D's code-trace is the **number**: 64.2 MiB peak per single in-flight icon resolution, multiplied by concurrent dashboard loads, from a *monitored site* — the exact adversary this system exists to watch. A 256 MiB homepage fetch costs ≈512 MiB.
  Honest limit: reachable only when an admin enables favicon resolution (default OFF) and only for sites with a stale/absent icon row (30-day ok-refresh, 24 h negative cache — `site_icons.py:63-64`), which is the docstring's own throttle but not a memory bound.
- **Cross-subsystem interactions:** the fetch runs on the **API** event loop (`app/routers/sites.py:560`), so a memory spike there takes out the API, not just the icon resolver.

---

### [CONFIRMED] AUDIT-4D-5 / -4D-6 / -4D-7 / -4D-8 — four delivery-path gaps, all still present, none changed
All four re-verified cold against HEAD; none has changed.
- **Severity:** **Low** (all four, unchanged) — each is a bounded, visible, non-corrupting degradation rather than a silent success.
- **Subsystem / file(s):** as enumerated per item below.
- **Verification method:** code-trace against HEAD `701552e`, plus the 4D repro suite re-run in this session's regression batch.
- **Deeper analysis:** these are the *narrow* findings in this scope; Session A's effort went to the *wide* ones (4D-1's reachability, the retry-storm model in AUDIT-SA5-6b, and the unsigned-webhook question in AUDIT-SA5-7b). No item here was refuted or extended by measurement.
- **Cross-subsystem interactions:** all four are internal to delivery (`worker/alert_tasks.py`, `worker/beat_tasks.py`, `app/remediation.py`, `app/explain.py`); their observable surface is the `alerts.tsx` / `remediation.tsx` views, which show whatever rows exist — which is precisely why the no-row failures (4D-1, 4D-6) are the dangerous ones.

- **AUDIT-4D-5 (Low)** — auto-fire cooldown anchored to `created_at`. `backend/app/remediation.py:124-138` uses `func.max(RemediationExecution.created_at)` over `queued|succeeded|failed`; `executed_at` (the actual outbound stamp, written at `remediation_tasks.py:66,109`) is never consulted. Bounded harm: at most one extra unattended firing at a window boundary; the conservative direction (downgrade to the confirm queue) is preserved and manual-confirm hooks are unaffected.
- **AUDIT-4D-6 (Low)** — channel-less alerts are re-swept forever. `backend/worker/alert_tasks.py:101-103` returns `"no-channels"` writing **no** row; `backend/worker/beat_tasks.py:340-350` matches on `having(count(AlertDelivery.id) == 0)`, so the predicate never clears. Steady state per stranded alert: one indexed SELECT + one `send_task` every 5 min, capped at `REDELIVERY_MAX_PER_RUN = 200` per run.
- **AUDIT-4D-7 (Low)** — flipping `requires_manual_confirm` to `True` does not recall queued firings. `app/routers/remediation.py::update_hook` updates the hook only; no UPDATE touches existing `queued` executions, and `worker/remediation_tasks.py:45-70` fires any `queued` row inside its `STALE_INFLIGHT` lease. Approval gating is evaluated at execution-creation time only.
- **AUDIT-4D-8 (Low)** — concurrent "explain this incident" requests both pay the LLM. `app/explain.py:146-184`: cache check (`:146`) → `resolve_task` (`:154`) → `task.generate` (`:177`) → `scan.explanation = text; await db.commit()` (`:181-184`), with no claim in between. At 4E's measured budget (AUDIT-4E-3) a 10-key hung pool makes each of the two racers stall ~300 s. Last-write-wins on valid text; no correctness or security impact.

---

### [NEW] AUDIT-SA5-6b — Alert delivery has **no retry at all** under a provider outage, and no circuit breaker
- **Severity:** **Low** — the finding is the *absence* of a retry path, and the outcome is visible (a `failed` row per channel), so it is not a silent failure. Recorded because the kickoff asked for the outage model and the answer is counter-intuitive.
- **Subsystem / file(s):** `backend/worker/alert_tasks.py:70-171`; `backend/worker/beat_tasks.py:327-376`; `backend/worker/celery_app.py` (no `autoretry_for` on `deliver_alert`).
- **Verification method:** code-trace + arithmetic from the measured constants.
- **Evidence (SMTP down for one hour, N flagged scans, C channels, W warm workers):**
  - Each alert is enqueued **once** by `scan_tasks` and delivered **once**. `_deliver_alert` writes one `AlertDelivery` row per channel with `status=failed`, `detail="Could not connect to SMTP server …"` (`alerting.py:164,168`). There is no Celery retry, no backoff, and no re-enqueue: `beat_tasks.py:340-350` requires **zero** delivery rows, and these alerts have *C* rows, so the resweep **never** re-touches them. ⇒ **1 attempt per alert, ever. 0 retries.**
  - Row growth is therefore **bounded and linear**: N alerts × C channels = N·C rows, one time. The "retry storm" the kickoff asked about cannot occur on the outage path.
  - The *only* unbounded-work path is the crash path: an alert whose worker died before its first commit has zero rows, so every sweep re-enqueues it. At the cap that is 200 alerts × 20 s of SMTP connect timeout = ~67 min of one worker's time **per 5-minute sweep** — the sweep can saturate the whole warm pool for over an hour. That is the real storm shape, and it is the inverse of the one usually feared.
  - No circuit breaker exists, so an SMTP host that black-holes connections produces N·C×20 s of stalled worker time per alert batch with no global throttle.
- **Cross-subsystem interactions:** `worker/celery_app.py` worker-pool sizing (Phase 9's territory) determines how badly the crash-path saturation hurts concurrent scans; `app/scanning` adaptive cadence determines how many flagged scans arrive per hour.

---

### [NEW] AUDIT-SA5-7b — Remediation webhook payloads carry **no authentication and no replay protection**
- **Severity:** **Low** — the payload contains no secret and the target is admin-configured. Graded Low, not High: forging a payload requires *being* the receiver's intended caller in spirit, and the exposure is receiver-side, not Wardress-side. Phase 10 may reasonably weigh this higher given that the receiver restarts containers.
- **Subsystem / file(s):** `backend/app/remediation.py:69-85` `build_remediation_payload`, `:172-201` `post_webhook`; `backend/worker/remediation_tasks.py:92-96`.
- **Verification method:** code-trace.
- **Evidence / the questions asked, answered:**
  - **What authentication does the outbound webhook carry?** **None.** `post_webhook` sets no headers beyond httpx's defaults — no `Authorization`, no shared secret, **no HMAC signature**, no timestamp. The URL is validated and DNS-pinned at fire time (`transport=SSRFPinningTransport(allow_private_networks=hook.allow_private_networks)`, `:182-185`) and encrypted at rest (`:29`), so the *channel* is as private as the URL, but nothing authenticates the *message*.
  - **Is the target SSRF-checked and pinned?** **Yes**, and this is the strongest part of the delivery subsystem: create/update validate via `assert_url_allowed`; every fire resolves, validates and connects to the same address. (`ssrf.py` itself untouched.)
  - **Is the payload sensitive?** No secret. Measured content: `event`, `action_type`, `hook_name`, `site.{id,name,url}`, `scan.{id,risk_score,verdict,detected_at}`, `dashboard_url`. The site URL and name are operator-supplied; the dashboard link is guessable-by-construction but the dashboard requires auth.
  - **Is there replay protection?** **No.** No nonce, no timestamp, no idempotency key. A receiver that knows the Wardress URL can be POSTed by anyone who learns it; and per AUDIT-2B-3's accepted residue, the lease-reclaim path re-POSTs the *same* payload after `STALE_INFLIGHT`, so **Wardress itself** can deliver a duplicate without knowing whether the first landed. `scan.id` is the only dedupe handle a receiver has.
  - **Can an attacker who observes one payload forge another?** **Yes, trivially** — an unsigned JSON document with a fully predictable schema, with nothing binding it to a Wardress instance.
- **Deeper analysis:** the receiver of a remediation webhook is, by design, something that restarts a container or rolls back a deploy. An unsigned, replayable POST to that receiver, over a URL that may be plain-HTTP on a LAN, is the weakest link in the "human-approval gating is solid" story 4D verified. 4D's own O-4D-3 idea (an `Idempotency-Key` header) is the cheap half; `X-Wardress-Signature: HMAC-SHA256(hook_secret, body)` plus a stored per-hook secret is the complete half, and the schema has a natural home for the secret next to `webhook_url_encrypted`.

---

## 3. Verified-clean ledger (fresh-eyes, evidence per item)

| Item | Verdict | Evidence |
|---|---|---|
| Fernet-at-rest on **every** AI credential write path | **VERIFIED** | Only two `credentials_encrypted=` assignment sites exist in the whole backend (`ai_config.py:130` `create_provider`, `:160` `update_provider`), both through `encrypt_keys → encrypt_json → Fernet`. Every AI route (legacy Gemini single-key/pool add/remove at `settings.py:414,454,457,496`; legacy Ollama at `:555,564`; unified `POST`/`PATCH` at `:671,699`) funnels through those two. Ciphertext ≠ plaintext and no secret appears in `provider_out`. |
| Key material never leaves the backend | **VERIFIED** | `provider_out` returns `key_hints` only (`ai_config.py:68-70` → `llm._key_hint`); audit snapshots record `key_count`/`keys_changed`; `decrypt_provider_blob` (`ai_config.py:253`) is **dead code** (§7) and returns nothing to any client. |
| `crypto.py` refuses to be guessable | **VERIFIED** | `config.py:25-39` validators reject a `CREDENTIALS_ENCRYPTION_KEY` or `JWT_SECRET` under 32 bytes **at startup** (pydantic `field_validator`); a wrong key surfaces as `DecryptionError`, which every caller degrades on. |
| Detection's second opinion can never blind the engine | **VERIFIED** | `llm_escalation.py:44-45` `should_escalate` requires `changed and 0.40 <= risk < 0.75`; the block is skipped when already `flagged`; `escalation_upgrades_verdict` (`:81-88`) returns True only for `defacement` at confidence ≥ 0.6, so the LLM can only raise attention; `parse_classification` (`llm.py:472-504`) rejects non-JSON/mis-classified/unparseable; `escalate_scan` catches `LLMUnavailable` **and** bare `Exception`; the block is `await`ed as a plain coroutine, so no Celery retry and no exception can escape the scan. |
| No retry/backoff storms in the AI path | **VERIFIED** | `llm.py:269` sets `num_retries` on the Router only; no `autoretry_for` anywhere in the AI path; `drop_params/telemetry/suppress_debug_info` set once at `:56-58`; Router cooldown (`allowed_fails=0`, 60 s) prevents a hot loop. |
| Partial/garbage provider responses | **VERIFIED** | `_MAX_OUTPUT_CHARS = 4_000` truncation (`llm.py:83,210`); `parse_classification`'s strict-JSON-first + non-greedy-fence fallback; `confidence` clamped to [0,1]; `rationale` capped at 500; `validation_detail` capped at 500 before persisting (`settings.py:760`). |
| Startup resilience | **VERIFIED** | `ai_startup.bootstrap_migration`/`bootstrap_catalog` swallow every exception with `logger.exception` (`:28-29`, `:39-40`); `sync_catalog`'s fallback ladder is live-consistent (**measured live**: 8 323 models / 225 providers retained in the DB); `upsert_catalog` refuses an empty model set (`ai_catalog.py:167-169`). |
| Legacy migration & seeding idempotence | **VERIFIED** | `migrate_legacy_ai_settings` no-ops once any provider exists (`:63-64`) and handles both legacy Gemini shapes; `seed_default_ollama_provider` is gated by the `ai_seed_done` sentinel **and** the "any provider exists" check (`:131-138`). Live state matches: sentinel present, exactly one seeded provider, zero assignments. |
| Deprecated adapters write through the new tables | **VERIFIED** | `/api/settings/gemini*` and `/api/settings/ollama*` read/write `ai_providers`/`ai_task_assignments` via the same service layer; legacy `app_settings` rows are no longer a source of truth (the only divergence is AUDIT-4E-1's missing save-time check). |
| `check_torch_osv.py` is wired into CI **and** can fail the build | **VERIFIED (re-run today)** | `ci.yml:67-70` runs it as its own step with no `|| true`. Live run: `auditing locked torch (2.13.0, 2.13.0+cpu; upstream versions 2.13.0)` / `torch 2.13.0: no known advisories` → **exit 0**. Non-vacuous (torch `2.13.0+cpu` present, local label stripped), fail-closed on OSV unreachability (exit 2) by design. |
| `alembic check` (model/migration drift) | **VERIFIED (re-run today)** | `alembic upgrade head` → exit 0; `alembic check` → **exit 0, "No new upgrade operations detected"** against the alembic-migrated schema on `wardress-test-pg:5433/wardress_sa_ai_test`. |
| No default credentials; `.env.example` placeholders | **VERIFIED** | Every secret is `CHANGE_ME_…`; `install.ps1:199-250` generates with a CSPRNG, then **asserts no assignment line still contains `CHANGE_ME`** and deletes the file + fails hard if one survived; a pre-existing `.env` with placeholders is refused (`:249-250`); `.env` is gitignored. `docker-compose.yml` uses `${POSTGRES_PASSWORD:?}`/`${JWT_SECRET:?}`/`${CREDENTIALS_ENCRYPTION_KEY:?}`. `ADMIN_PASSWORD` is empty by default with `seed_admin.MIN_PASSWORD_LENGTH = 12`. |
| `scripts/update.ps1` does not regenerate secrets | **VERIFIED (new)** | Zero matches for `CHANGE_ME`, `CREDENTIALS_ENCRYPTION_KEY`, `JWT_SECRET`, `POSTGRES_PASSWORD` in `scripts/update.ps1` — a routine upgrade does **not** trigger AUDIT-SA5-3. |
| WeasyPrint advisory reachability | **UNCHANGED from 4E** | `app/routers/reports.py:195-199` is the sole call site: `HTML(string=html).write_pdf()` with no `stylesheets=`, no `xmp_metadata=`, no `url_fetcher=` — the advisory's two exploit channels are exactly those parameters, and the HTML is template-built with autoescape plus data-URI screenshots and one inline SVG. |
| Email HTML body: no HTML injection | **VERIFIED (new)** | Jinja `select_autoescape(["html"])` (`alerting.py:36-39`); **no `|safe` in any of the three templates**; a hostile `site_name` is escaped and survives `premailer.transform`; `Bcc`/header injection is refused by `EmailMessage`. The one path that *does* break is the SMTP-header construction itself (AUDIT-4D-1), not the body. |
| Remediation webhook SSRF posture | **VERIFIED (strongest part of the subsystem)** | Save-time `assert_url_allowed` + fire-time `SSRFPinningTransport` with the hook's own opt-in flag; the URL is never echoed into the failure detail (`:190-193`). |
| Docker build hygiene (dependency layer, apt cleanup) | **VERIFIED** | Dependency layer before source copy in both Dockerfiles; `uv sync --frozen --no-dev` in both; every `apt-get install` ends with `rm -rf /var/lib/apt/lists/*`; the Playwright base tag deliberately tracks the `playwright==1.61.0` pin (documented in three places); MiniLM pre-baked so a scan never needs HuggingFace at runtime (with the two caveats in AUDIT-4E-5). |
| GitHub Actions SHA pinning + least privilege | **VERIFIED** | All 5 checkout steps and every other action are SHA-pinned with version comments; `ci.yml` top-level `permissions: contents: read`; per-ref `concurrency` never cancelling `main`; `uv` 0.9.2 consistent across CI and both Dockerfiles; pnpm 11.13.1 consistent between `ci.yml:135` and `walkthrough/package.json`. |

---

## 4. Supply-Chain Sweep Results

Every gate, the exact command, the exit code, the output, and the honest limits of the method.

| # | Gate | Command (run from) | Exit | Result |
|---|---|---|---|---|
| 1 | Backend dependency audit (CI-equivalent) | `cd backend; uv run --frozen pip-audit --skip-editable` | **1** | `Found 12 known vulnerabilities in 3 packages` — `oauthlib 3.3.1` CVE-2026-49265; `pyjwt 2.13.0` ×10 (CVE-2026-102265/102267/102268/102269/102271/102272/102273/102274, CVE-2026-101917) all fix `2.14.0`; `weasyprint 69.0` PYSEC-2026-3940 fix `70.0` |
| 2 | Backend dependency audit, machine-readable | `cd backend; uv run --frozen pip-audit --skip-editable --format json` | **1** | Per-advisory descriptions, aliases, CVSS vectors and maintainer timelines captured to scratch; used for the reachability triage in AUDIT-SA5-1 |
| 3 | torch cross-check vs OSV (CI-equivalent) | `cd backend; uv run --frozen python tools/check_torch_osv.py` | **0** | `auditing locked torch (2.13.0, 2.13.0+cpu; upstream versions 2.13.0)` / `torch 2.13.0: no known advisories` |
| 4 | Frontend dependency audit (CI-equivalent) | `cd frontend; pnpm audit --audit-level high` | **1** | `12 vulnerabilities found / Severity: 3 low | 7 moderate | 2 high` — 2 HIGH `undici` (`GHSA-rfgv-xxqx-mfg5`, `GHSA-w293-vg96-wgc3`), path `.>vitest>jsdom>undici` |
| 5 | Frontend dependency audit, all severities | `cd frontend; pnpm audit` | **1** | Same 12; adds the 2 `vitest`/`@vitest/mocker` moderates (`GHSA-82fw-gwwq-j7x9`, patch `>=4.1.11`) and 3 low |
| 6 | **Walkthrough dependency audit (NO CI GATE EXISTS)** | `cd walkthrough; pnpm audit --audit-level high` | **1** | `8 vulnerabilities found / Severity: 1 low | 6 moderate | 1 high` — HIGH `nanoid` `GHSA-2v37-7h3g-55p8` `<3.3.18`; moderates incl. `mermaid <11.16.1` `GHSA-c4c3-pg64-4m4v` |
| 7 | Backend lint (CI step 1) | `cd backend; uv run --frozen ruff check .` | **1** | `Found 9 errors` (HEAD baseline) — `I001`, `F401`, and `S603/S110/ASYNC240/ASYNC230/E501×3` in `tools/run_stress_catalog.py` |
| 8 | Backend format (CI step 2) | `cd backend; uv run --frozen ruff format --check .` | **1** | `24 files would be reformatted, 168 files already formatted` — identical count to 4E |
| 9 | New test file lint | `cd backend; uv run --frozen ruff check tests/test_phase_sa5_ai_infra_repros.py` | **0** | `All checks passed!` |
| 10 | New test file format | `cd backend; uv run --frozen ruff format --check tests/test_phase_sa5_ai_infra_repros.py` | **0** | `1 file already formatted` |
| 11 | Migration drift (CI `migrations` job) | `cd backend; $env:DATABASE_URL="postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_ai_test"; uv run --frozen alembic check` | **0** | `No new upgrade operations detected` (after `alembic upgrade head` → exit 0) |
| 12 | Locked-version inventory | `cd backend; uv run --frozen python <reverse-dep probe>` | 0 | `pyjwt 2.13.0`, `litellm 1.93.0`, `apprise 1.12.0`, `weasyprint 69.0`, `requests 2.34.2`, `oauthlib 3.3.1`, `requests-oauthlib 2.0.0`, `cryptography 50.0.0`, `httpx 0.28.1`, `pydantic 2.13.4`, `starlette 1.3.1`, `fastapi 0.139.0`, `jinja2 3.1.6`, `pillow 12.3.0`, `lxml 6.1.1`, `anyio 4.14.2`, `urllib3 2.7.0`, `playwright 1.61.0`, `torch 2.13.0+cpu`, `scikit-learn 1.9.0`, `aiosqlite 0.22.1`; `werkzeug` and `apprise-telegram` **not installed** (nothing imports them). No advisory was reported against `jinja2 3.1.6`, `cryptography 50.0.0`, `pillow 12.3.0`, `lxml 6.1.1`, `starlette 1.3.1`, `fastapi 0.139.0`, `httpx 0.28.1`, `anyio 4.14.2`, `urllib3 2.7.0`, `requests 2.34.2` or `playwright 1.61.0`. |
| 13 | Dependency-graph provenance | `uv.lock` reverse-dependency scan | 0 | `oauthlib ← requests-oauthlib ← apprise`; `pyjwt`, `weasyprint`, `litellm`, `apprise` ← `wardress-backend` (direct runtime pins) |
| 14 | Dead-import scan for the two advisory packages | `rg "requests_oauthlib|import oauthlib"` over the repo | — | **zero hits** — the `oauthlib` PKCE advisory is unreachable from Wardress code |
| 15 | Runtime image inventory | `docker inspect --format '{{.Config.Image}}'` + `docker image inspect RepoDigests` | 0 | See AUDIT-4E-5's table; no `@sha256` in any Dockerfile or in the compose file |
| 16 | Build-context hygiene | `docker exec wardress-app-1 ls -la /app` + `git status --ignored backend/` | — | `build_app.err.log` (56 B) and `build_app.log` present in the image, absent from git, absent from `.dockerignore` (AUDIT-SA5-5) |
| 17 | Image-vs-lockfile package spot check | `docker exec wardress-app-1 python -c "import importlib.metadata…"` | 0 | `httptools 0.8.0`, `h11 0.16.0`, `uvicorn 0.51.0` — all consistent with `uvicorn[standard]` in the lock |
| 18 | Installed-vs-source parity | `docker cp` + `git hash-object` over 27 files | 0 | **27/27 MATCH** (§6) |

### Honest limits of this sweep — stated, not glossed

1. **`pip-audit` cannot see `torch`.** Its own output says so: `torch — Dependency not found on PyPI and could not be audited: torch (2.13.0+cpu)`. This is closed *only* for torch, by gate 3. Any other local-version-labelled or non-PyPI artifact in the lockfile would be silently skipped the same way — `uv.lock` was scanned and torch is the only `+`-suffixed version, so the exposure is bounded *in this lockfile*, but the *method* has the hole.
2. **`pip-audit` audits the installed environment, not the two Docker images.** No gate compares `pip list` inside `wardress-app-1`/`wardress-worker-1` against `pyproject.toml`. My parity check covered 27 named files; it did **not** enumerate every installed distribution, so a package present in an image but absent from the lockfile cannot be ruled out by this report. (Gate 17 is a 3-package spot check only.)
3. **`pip-audit` knows only what PyPI's advisory feed contains.** Eleven of today's twelve did not exist at the last recorded sweep. The feed is also ecosystem-scoped: a GitHub-only advisory with no PyPI alias, or a malicious package with no advisory at all, is invisible to this method by construction.
4. **`pnpm audit` is severity-thresholded in CI** (`--audit-level high`), so moderate/low advisories never fail a build. Gate 5 (`pnpm audit`, no threshold) was run manually to see them; nothing in CI does.
5. **The `walkthrough/` tree has no audit gate at all** (gate 6 was run by hand). Its lockfile is a second, entirely ungated dependency tree that `static.yml` publishes.
6. **No SCA/SBOM/lockfile-diff tooling exists in this environment** — no Dependabot, no Renovate, no Trivy/Grype, no OSV batch client beyond `check_torch_osv.py`'s single-purpose query, no `pip-audit -r`. "Vulnerability sweep" in this report means exactly the seven commands in gates 1–6 plus gates 11–18, run fresh.
7. **Neither Docker image is built in CI** (AUDIT-SA5-4), so no scan of the *actual shipped artifacts* is possible in this environment at all.
8. **`ruff check` / `ruff format` counts are a moving target** because four subagents are adding test files concurrently. Gates 7–8 are the HEAD baseline measured at the start of this subagent's session; the later 26/28 counts belong to other subagents' files.
9. **No frontend test suite or build was run** — `pnpm lint` / `tsc -b` / `vitest` are Phase 4F/9 territory and re-running them would consume their evidence window. The frontend dependency gate (`pnpm audit`) is the 4E gate and was run.

### Is CI green now? — **No.**

| Job | Gate | Status |
|---|---|---|
| `backend` | `ruff check .` | **RED** — 9 errors (step 1 of 4; nothing after it runs) |
| `backend` | `ruff format --check .` | **RED** — 24 files (never reached) |
| `backend` | `pip-audit --skip-editable` | **RED** — 12 advisories (never reached) |
| `backend` | `check_torch_osv.py` | GREEN (exit 0) — never reached |
| `backend` | `pytest -q` | never reached |
| `migrations` | `alembic upgrade` / round-trip / `alembic check` | **GREEN** — all three pass (re-verified locally) |
| `frontend` | `pnpm audit --audit-level high` | **RED** — 2 HIGH `undici` |
| `frontend` | `pnpm lint`, `tsc -b`, `vitest run`, `pnpm build` | not re-run (4F/9 territory); 4F recorded lint + typecheck + 144 tests green |
| `docker` | `docker compose config --quiet` | **GREEN** — but it validates nothing about the images (AUDIT-SA5-4) |
| *(none)* | walkthrough audit / lint / test | **NO GATE EXISTS** |

**Verdict:** the security-relevant gates are red on **both** dependency trees, and the backend lint/format gate masks every gate behind it. `weasyprint` was not bumped; the eleven new advisories are in `pyjwt` and `oauthlib`.

---

## 5. Env-Variable Cross-Reference

Enumerated by grepping `os.getenv` / `os.environ` / `getenv(` / `os.environ[...]` over `backend/` (excluding `.venv` and tests), every pydantic-settings field in `backend/app/config.py`, and `process.env` / `import.meta.env` over `frontend/`.

| variable | read where | in `.env.example`? | forwarded in compose? | status |
|---|---|---|---|---|
| `DATABASE_URL` | `app/config.py:17`; `alembic/env.py:17`; `worker/db.py:16`; `app/db.py:21`; `app/seed_admin.py:41` | ✅ `:18` | ✅ app/worker/beat/telegram-bot | OK |
| `REDIS_URL` | `app/config.py:18`; `worker/celery_app.py:13-14`; `worker/beat_tasks.py:92` | ✅ `:21` | ✅ app/worker/beat/telegram-bot | OK |
| `JWT_SECRET` | `app/config.py:19,32-39`; `app/security.py:51,60` | ✅ `:24` | ✅ app/worker/beat/telegram-bot | OK — validator ≥ 32 bytes |
| `CREDENTIALS_ENCRYPTION_KEY` | `app/config.py:23,25-29`; `app/crypto.py:32` | ✅ `:25` | ✅ app/worker/beat/telegram-bot | OK — validator ≥ 32 bytes. **Rotation consequences undocumented** (AUDIT-SA5-3) |
| `ADMIN_EMAIL` | `app/seed_admin.py:27` | ✅ `:29` | ✅ app | OK |
| `ADMIN_PASSWORD` | `app/seed_admin.py:28` | ✅ `:30` | ✅ app | OK |
| `ADMIN_RESET_PASSWORD` | `app/seed_admin.py:29` | ✅ `:37` | ✅ app (default `false`) | OK — documented emergency knob |
| `TELEGRAM_BOT_TOKEN` | `worker/telegram_bot.py:87,107` | ✅ `:51` | ✅ telegram-bot only (default empty) | OK — profile-gated |
| `RATE_LIMIT_PER_IP` | `app/config.py:79` → `app/ratelimit.py` | ✅ `:55` | ✅ app | OK |
| `RATE_LIMIT_PER_USER` | `app/config.py:80` | ✅ `:56` | ✅ app | OK |
| `RATE_LIMIT_WINDOW_SECONDS` | `app/config.py:81` | ✅ `:57` | ✅ app | OK |
| **`LOGIN_RATE_LIMIT_PER_IP`** | `app/config.py:86` → `app/ratelimit.py`; set in `tests/conftest.py:33`, `tests/test_phase17_auth_audit.py:211,226` | ❌ **MISSING** | ❌ **MISSING** | **GAP — AUDIT-SA5-7.** Permanently pinned at the code default 30. The tightest security knob in the system is untunable and undocumented. |
| `TRUST_PROXY_HEADERS` | `app/config.py:91` | ✅ `:59` | ✅ app | OK |
| `CORS_ALLOWED_ORIGINS` | `app/config.py:96,99` | ✅ `:87` | ✅ app | OK |
| `MAX_REQUEST_BODY_BYTES` | `app/config.py:87` | ✅ `:74` | ✅ app | OK |
| `ACCESS_TOKEN_TTL` | `app/config.py:43` | ✅ `:70` | ✅ app | OK |
| `REFRESH_TOKEN_TTL` | `app/config.py:44` | ✅ `:71` | ✅ app | OK |
| `MAX_SESSION_TTL` | `app/config.py:48` | ✅ `:72` | ✅ app | OK |
| `JWT_LEEWAY_SECONDS` | `app/config.py:51` | ✅ `:73` | ✅ app | OK |
| `COOKIE_SECURE` | `app/config.py:60` | ✅ `:95` | ✅ app | OK |
| `PUBLIC_BASE_URL` | `app/config.py:72`; `app/alerting.py:121`; `app/remediation.py:72` | ✅ `:12` | ✅ app/worker | OK |
| `ARTIFACTS_DIR` | `app/config.py:56` | ✅ (documented as **not** forwarded, `:76-81`) | ❌ **by design** | OK — the honest pattern; the exclusion is documented in all three places |
| `WARDRESS_HTTP_PORT` | **`docker-compose.yml` only** (port mapping + `PUBLIC_BASE_URL` default) | ✅ `:9` | n/a (compose-level) | OK — not an app setting |
| `HF_HUB_OFFLINE` | `backend/tools/build_fusion_dataset.py:51` (build-time only) | n/a | n/a | OK — tool-scoped, not runtime |
| `CAPTURE_E2E_REPORT`, `CAPTURE_E2E_KEEP_CHILD`, `CAPTURE_CHILD_OUT` | `backend/tests/test_capture_e2e.py`, `tests/_capture_child_impl.py` | n/a | n/a | OK — test-only |
| `SYSTEMROOT`, `TEMP` | `backend/tools/run_stress_catalog.py:38`; `tests/test_capture_e2e.py:262,337` | n/a | n/a | OK — OS-provided |
| *(frontend)* `import.meta.env.*` / `process.env.*` | **zero occurrences** anywhere in `frontend/src`, `frontend/tests`, `vite.config.ts` | n/a | n/a | OK — the SPA is same-origin and needs no build-time env |

**Summary: 1 gap (`LOGIN_RATE_LIMIT_PER_IP`). 0 documented-but-unread. 1 deliberate, correctly-documented exclusion (`ARTIFACTS_DIR`).**

---

## 6. Deployment Parity

Method: `docker cp` each file out of the running container, then `git hash-object` both the container copy and the working-tree file. **No container was started, stopped, rebuilt or pulled.**

| file | container hash-object | HEAD hash-object | MATCH/DIFF |
|---|---|---|---|
| `app/ai_config.py` | `1ac5fd16e568af7be1440ef0e7bec948ad97d4ad` | `1ac5fd16e568af7be1440ef0e7bec948ad97d4ad` | **MATCH** |
| `app/ai_catalog.py` | `f9460a8f194990e9faaba75c1b9e6b79549d8e97` | `f9460a8f194990e9faaba75c1b9e6b79549d8e97` | **MATCH** |
| `app/ai_ollama.py` | `ccffe0ac92b437dfc594dcb1e76c99b01d186fe8` | `ccffe0ac92b437dfc594dcb1e76c99b01d186fe8` | **MATCH** |
| `app/ai_startup.py` | `ccdc93919eb72a4e756252847db13fb5ba696b19` | `ccdc93919eb72a4e756252847db13fb5ba696b19` | **MATCH** |
| `app/ai_migration.py` | `5c01930bb0e411e87dcd7a127650781ae3f34ee6` | `5c01930bb0e411e87dcd7a127650781ae3f34ee6` | **MATCH** |
| `app/llm.py` | `72a49f974164e02eaec4af57519b408832b75e8b` | `72a49f974164e02eaec4af57519b408832b75e8b` | **MATCH** |
| `app/crypto.py` | `dbcfecce1e50a39498b21602226fa75560d79719` | `dbcfecce1e50a39498b21602226fa75560d79719` | **MATCH** |
| `app/explain.py` | `efb4910f5fe6da79ea3541b267bd3f58c6783cb3` | `efb4910f5fe6da79ea3541b267bd3f58c6783cb3` | **MATCH** |
| `app/alerting.py` | `7153c563afc4339446de3e964b5744ee020dd907` | `7153c563afc4339446de3e964b5744ee020dd907` | **MATCH** |
| `app/remediation.py` | `2cbb9c6adf06e14bca81236181cc445e291997ed` | `2cbb9c6adf06e14bca81236181cc445e291997ed` | **MATCH** |
| `app/site_icons.py` | `0564620e20cdd05b17179290e9187fa7fb718d73` | `0564620e20cdd05b17179290e9187fa7fb718d73` | **MATCH** |
| `app/routers/settings.py` | `b0a23c7131393478c8e40ba9a6c77d2ecde81c2f` | `b0a23c7131393478c8e40ba9a6c77d2ecde81c2f` | **MATCH** |
| `app/config.py` | `2705b158a476b3cfbea50ad42cd9d9d89206ac00` | `2705b158a476b3cfbea50ad42cd9d9d89206ac00` | **MATCH** |
| `app/security.py` | `9c15dbd95de90f135b9b35d0decb56ad1a9a93da` | `9c15dbd95de90f135b9b35d0decb56ad1a9a93da` | **MATCH** |
| `app/ssrf.py` | `e792b445f45bc38081201777b780a4bd27f1997d` | `e792b445f45bc38081201777b780a4bd27f1997d` | **MATCH** |
| `app/ssrf_transport.py` | `e790d58a1765c61149a2ba61f16e6a9215c5f829` | `e790d58a1765c61149a2ba61f16e6a9215c5f829` | **MATCH** |
| `app/templates/email/alert.html` | `b28d54338d26ddf5314b8bd14475bb3aa4ff14e0` | `b28d54338d26ddf5314b8bd14475bb3aa4ff14e0` | **MATCH** |
| `app/templates/email/test.html` | `547ad5859b35c05f78338598ec79efde76215b00` | `547ad5859b35c05f78338598ec79efde76215b00` | **MATCH** |
| `app/templates/report/report.html` | `44fd99aa2de361ed555cd3e8db0464de33717992` | `44fd99aa2de361ed555cd3e8db0464de33717992` | **MATCH** |
| `app/data/models_dev_catalog.json` | `49485929fe3554020f4d7b5e7adda3bc97b1aad3` | `49485929fe3554020f4d7b5e7adda3bc97b1aad3` | **MATCH** |
| `pyproject.toml` | `65a976f3d3b886c66a0b37ebb7f31ddcf8eee9f8` | `65a976f3d3b886c66a0b37ebb7f31ddcf8eee9f8` | **MATCH** |
| `uv.lock` | `4c5cb7e31fcfa6b14404f0db19e073b033f7c909` | `4c5cb7e31fcfa6b14404f0db19e073b033f7c909` | **MATCH** |
| `worker/llm_escalation.py` (worker ctr) | `c8403273a312cbe57516303d56b5614b6c37c579` | `c8403273a312cbe57516303d56b5614b6c37c579` | **MATCH** |
| `worker/alert_tasks.py` (worker ctr) | `d846e9a9ceac04f60c2196f9b189086dce072de8` | `d846e9a9ceac04f60c2196f9b189086dce072de8` | **MATCH** |
| `worker/remediation_tasks.py` (worker ctr) | `ca5ae786c47b18315197f254b700f25eca8c223a` | `ca5ae786c47b18315197f254b700f25eca8c223a` | **MATCH** |
| `worker/beat_tasks.py` (worker ctr) | `f11b6fce7f493e5f27ff15fe3e1babd388d2ae21` | `f11b6fce7f493e5f27ff15fe3e1babd388d2ae21` | **MATCH** |
| `worker/celery_app.py` (worker ctr) | `ce392754830abdb15d8e83769c18dd77fdbf4623` | `ce392754830abdb15d8e83769c18dd77fdbf4623` | **MATCH** |

**27/27 MATCH.** Every live-probe conclusion in this report is therefore a statement about HEAD. This **closes AUDIT-4B-8's parity precondition** for my scope: the stack is fully in parity with the working tree, so no finding here is invalidated by a stale build.

---

## 7. Dead Code & Orphan Routines

Proven by repo-wide `rg -w` over `backend/` (excluding `.venv`), with occurrence-level hit lists.

| file:line | symbol | kind | proof (grep hits) |
|---|---|---|---|
| `backend/app/ai_config.py:253` | `decrypt_provider_blob` | **Orphaned function + latent secret-exfiltration surface** | Exactly **1** hit repo-wide — its own `def`. Docstring says "migration/debug only — never returned to a client", but no migration, router, tool or test calls it. Returns the **full decrypted `{api_keys: [...]}` blob**. `ruff` does not flag it (module-level `def`, not an unused import). |
| `backend/app/ai_config.py:249` | `catalog_supports_tools_sync` | **Orphaned function** | Exactly **1** hit repo-wide — its own `def`. The live tool-calling gate is `resolve_tool_capability` (`:227-246`), which reads the DB directly; this sync wrapper is unreachable. |
| `backend/app/llm.py:398-407` vs `backend/worker/alert_tasks.py:36-45` | `LAYER_LABELS` | **Duplicated constant (divergence hazard)** | Two independent 8-key copies of the same layer-label map. `llm.py`'s is read only by `_summarize_layers` (`:414`); `alert_tasks.py`'s only by `top_layers_from_scores` (`:55,57`). Adding or renaming a layer requires editing both; nothing enforces that. |
| `backend/app/models.py:862` | comment referencing `_key_hint` | **Stale comment** | The comment says "hint-only, like the old `_key_hint`" — `_key_hint` now lives in `app/llm.py:99`. Harmless but misleading (Rule 13 class). |
| `backend/app/ai_config.py:59` | `MAX_KEYS_PER_PROVIDER` | *Not dead*, but inconsistently enforced | Enforced on the deprecated Gemini pool path (`settings.py:450`) and **not** on the current `POST /api/settings/ai/providers` path — so the unified UI can exceed the 10-deployment budget that AUDIT-4E-3's ~300 s arithmetic assumes. Cross-reference, not a new finding. |
| `backend/app/ssrf.py:53` | `resolve_host` | *Not dead* | Used by `assert_url_allowed:107` and imported by `app/ssrf_transport.py`. Recorded to show it was checked. |
| `backend/app/ai_ollama.py:27` | `OLLAMA_CLOUD_HOST` | *Not dead* | Used once at `:62`. |
| `backend/app/ai_ollama.py:87` | `show_capabilities` | *Not dead* — and the SSRF path | Used by `model_supports_tools:111`, the unvalidated reader in AUDIT-4E-1. |
| `backend/app/ai_catalog.py:45` | `PROVIDER_LITELLM_PREFIX` | *Not dead* | Used at `:68`. |
| `backend/app/llm.py:178` | `_signature` | *Not dead* | Used at `:303`. |
| `backend/app/site_icons.py:155` | `extract_icon_href` | *Not dead* | Used at `:216`. |
| `backend/worker/alert_tasks.py:47` | `TOP_SIGNALS` | *Not dead* | Used at `:60`. |
| `backend/app/explain.py:25` | `_MAX_EVIDENCE_NOTES` | *Not dead* | Used at `:133`. |
| `backend/app/alerting.py:32` | `SEND_TIMEOUT_SECONDS` | *Not dead* | Used at `:146` and `:202`. |
| `backend/app/alerting.py:123` | `smtp_settings_usable` | *Not dead* | Used at `:130,231` and by `settings.py:98,170`. |
| `backend/app/alerting.py:183` | `_redact_apprise_failure` | *Not dead* | Used at `:206`. |
| `backend/app/ai_config.py:103` | `list_providers` | *Not dead* | Used by `settings.py:655`. |
| `backend/app/ai_catalog.py:129` | `load_snapshot` | *Not dead* | Used at `:227`. |
| `backend/app/site_icons.py:245` | `get_favicon_enabled` | *Not dead* | Used by `sites.py:560`. |
| `backend/app/site_icons.py:111` | `_gate_url` | *Not dead* | Used at `:133`. |
| `backend/app/alerting.py:177` | `build_telegram_apprise_url` | *Not dead* | Used at `:243` and `settings.py:286`. |
| `scripts/generate_structure.py` | — | *Not dead*, but barely referenced | Referenced in only 2 files repo-wide; not invoked by any workflow, compose service, or other script. A maintenance utility. |

**Dead-code count: 2 genuinely orphaned functions, 1 duplicated constant, 1 stale comment. No unused imports in my scope** (`ruff`'s `F401` fires only on other phases'/subagents' files).

---

## 8. Opportunities for Optimization

| proposal | target file(s) | measured / projected impact | risk |
|---|---|---|---|
| **Propagate a caller-owned deadline into the LLM layer** — wrap `escalate_scan` and `explain_scan`'s `task.generate` in `asyncio.wait_for` sized against the remaining scan budget (e.g. 20 % of `celery_app`'s 420 s soft limit) | `worker/llm_escalation.py:66`, `app/explain.py:177`, `app/llm.py:194-202` | Measured: a hung 1-key provider costs **30.0–31.6 s** (6 passes), a 10-key pool **~300 s**, with a fallback provider **~600 s** > the 420 s soft limit. A 60 s cap turns a soft-limit kill into a graceful evidence string. | Low — degradation is already the contract; only the bound changes. A `wait_for` cancellation is a `BaseException`, so an explicit guard is needed so it cannot escape into the scan. |
| **Key-pool sizing enforcement + UI hint** | `app/schemas.py` (`AiProviderCreate.api_keys`), `app/ai_config.create_provider`, `frontend/src/components/ai-settings-card.tsx` | `MAX_KEYS_PER_PROVIDER = 10` is enforced on the deprecated Gemini path (`settings.py:450`) and **not** on `POST /api/settings/ai/providers`, so the current UI can build an unbounded deployment list whose worst-case hang is `30 s × N`. Enforcing the cap in the service layer bounds the worst case at 300 s. | Low — additive validation; one HTTP 422 shape already exists. |
| **One shared outbound-fetch factory** (carry-forward of 4E's O-4E-1, now with five concrete call sites) | new helper in `app/ssrf_transport.py`; adopted by `app/ai_catalog.py:148`, `app/site_icons.py:193`, `app/ai_ollama.py:64,94,122` | Measured: `site_icons` builds its client with kwargs `['follow_redirects','timeout']` — **no `transport`**; `ai_catalog` with `timeout=20` and no `transport`; `ai_ollama` with none at all. One factory makes "forgot the policy" unrepresentable across all five. | Low-medium — the Ollama path needs a per-call `allow_private_networks` derived from the provider type, so the factory signature must carry it. |
| **Streaming size budget for the favicon fetch** | `app/site_icons.py:134,151` | Measured: a 32 MiB body costs **64.2 MiB** of Python heap on the **API event loop** before truncation. `client.stream()` with an incremental `max_bytes+1` budget caps it at 64 KiB + one chunk. | Low — mechanical, same public behaviour. |
| **Value-aware secret redaction** | `app/llm.py:60-79`; `app/models.py` (no schema change needed) | Constructed end-to-end: a 9-char custom key survives into the persisted `validation_detail`, the layer-8 evidence a **Viewer** can read, and an HTTP 503 body. Replacing the provider's own configured key values at log/response time closes all five sinks with no pattern heuristics at all. | Low — additive; the existing patterns stay as a backstop. Requires decrypting keys in the logging path, so it should *not* log the replacement value. |
| **Periodic dependency-audit artifact + health row** (carry-forward of 4E's O-4E-2, now with a number) | `backend/tools/` summary script, `app/routers/health.py`, `frontend/src/pages/health.tsx` | The gate went 1 → 12 advisories in eleven days and **no** self-hosted operator sees a red GitHub Actions run. Persisting `audit state: 12 advisories (pyjwt 2.13.0 → 2.14.0, oauthlib → 4.0.0, weasyprint 69.0 → 70.0)` as one health row makes supply-chain state operator-visible with no runtime network call. | Low — read-only artifact. |
| **AI-degradation rollup** (carry-forward of 4E's O-4E-3) | `worker/llm_escalation.py:70,75,78` (evidence already emitted), `app/routers/health.py`, `frontend/src/pages/health.tsx` | The escalation already records `ok` / `not configured` / `unavailable: …` / `unparseable reply` per scan. Live state right now: `ai_task_assignments` = **0 rows**, i.e. the feature is entirely inert on this install and nothing says so. | Low. |
| **litellm model-load caching is already correct — do not touch it** | `app/llm.py:173-175, 303-312, 344-358` | `_router_cache` is an `OrderedDict` LRU keyed on the rows' `updated_at` signature, max 32, behind an `asyncio.Lock`, with a double-checked insert (`:344-353`) and one-at-a-time eviction (`:357-358`) so cooldown state survives and a Settings edit takes effect immediately. Better than most hand-rolled pools. | None — recorded as a positive so a remediation prompt does not "fix" it. |
| **Catalog fetch scheduling is already reasonable** | `app/ai_catalog.py:144`, `worker/beat_tasks.py:76` | `CATALOG_REFRESH_SECONDS = 12 h` + once per app start; litellm's cost map loads from the package (4 436 entries, no network). 4E's O-4E-4 (memoize the validated address set) only becomes relevant once the fetch goes through the pinning transport. | None now; revisit after the factory lands. |
| **Alert-delivery batching — recommend AGAINST** | `worker/alert_tasks.py:125-166` | The per-channel `await db.commit()` (`:166`) is the right trade for crash-safety and costs < 1 % of the 20–40 s per-channel budget. Batching would **widen** the AUDIT-4D-1 orphan window. Recorded so the idea is not re-proposed. | Would regress AUDIT-4D-1. |
| **Docker build caching + pnpm pinning in the app image** | `backend/Dockerfile.app:9-13` | The Python layer already uses `--mount=type=cache,target=/root/.cache/uv` (`:27,32`); the frontend stage runs a bare `pnpm install --frozen-lockfile` (`:11`) with **no store cache**, so every app-image build re-downloads the whole pnpm store. Separately, `corepack enable` (`:9`) with no version + no `packageManager` in `frontend/package.json` means the app image can build with a different pnpm major than CI's pinned 11.13.1. Two lines, both large build-time wins / a real parity hole. | Low. |
| **Model-weight pinning** | `backend/Dockerfile.worker:27` | `SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')` resolves `main` — an unpinned floating reference that silently changes layer-8/9 embeddings (and therefore fused risk) with no code diff. Pin `revision=<sha>` and drop the `|| echo` so a failed pre-download **fails the build**. | Low — changes image size/contents; ship with the digest-pinning work. |
| **CI: split the backend gates + add a `docker build` job** | `.github/workflows/ci.yml:56-72, 154-165` | Today the first failing command aborts the step and masks three security gates. Four separate steps (or four jobs) make each reportable. A `docker build` job adds ~4 min of critical path but gates the artifact the operator actually runs. The four jobs are already independent, so no other parallelism is available. | Low. |

---

## 9. Summary

### Classification counts

| Classification | Count | IDs |
|---|---|---|
| **DEEPENED** | 12 | AUDIT-4E-1, AUDIT-4E-2, AUDIT-4E-3, AUDIT-4E-4, AUDIT-4E-5, AUDIT-4E-8, AUDIT-4E-10, AUDIT-4E-11, AUDIT-4D-1, AUDIT-4D-3, AUDIT-4D-4, and AUDIT-4D-2 (reachability analysis added) |
| **CONFIRMED** (unchanged) | 4 groups | AUDIT-4E-6, AUDIT-4E-7, AUDIT-4E-9, and AUDIT-4D-5/-4D-6/-4D-7/-4D-8 (grouped, all four) |
| **NEW** | 10 | AUDIT-SA5-1, AUDIT-SA5-2, AUDIT-SA5-3, AUDIT-SA5-4, AUDIT-SA5-5, AUDIT-SA5-6, AUDIT-SA5-7, AUDIT-SA5-8, AUDIT-SA5-6b, AUDIT-SA5-7b |
| **INVALIDATED** | **0** | Nothing in my scope was refuted. AUDIT-4B-8's *parity precondition* is resolved (27/27 MATCH), not the finding itself. |

### Severity distribution

| Severity | IDs |
|---|---|
| **Critical** | AUDIT-4E-1, AUDIT-4E-2, AUDIT-4E-4 |
| **High** | AUDIT-SA5-1, AUDIT-4E-8 *(up from Medium)*, AUDIT-4E-10 *(up from Low)*, AUDIT-4D-1 |
| **Medium** | AUDIT-4E-3, AUDIT-4E-5, AUDIT-4E-11, AUDIT-4D-2, AUDIT-4D-3, AUDIT-4D-4, AUDIT-SA5-3, AUDIT-SA5-4 |
| **Low** | AUDIT-4E-6, AUDIT-4E-7, AUDIT-4E-9, AUDIT-4D-5, AUDIT-4D-6, AUDIT-4D-7, AUDIT-4D-8, AUDIT-SA5-2, AUDIT-SA5-5, AUDIT-SA5-6, AUDIT-SA5-7, AUDIT-SA5-8, AUDIT-SA5-6b, AUDIT-SA5-7b |

### New test files added

| Path | What it proves | Status |
|---|---|---|
| `backend/tests/test_phase_sa5_ai_infra_repros.py` | **9 tests, all PASSING** (0 failed, 0 skipped), hermetic (no network, no DB, no container), `ruff check` **All checks passed!**, `ruff format --check` **1 file already formatted** | committed-ready; **not committed** (Rule 9/10 — this subagent does not commit) |

| Test | Proves |
|---|---|
| `test_resolve_tool_capability_never_consults_the_ssrf_policy` | AUDIT-4E-1 — the agent-chat tool gate POSTs to the stored `base_url` with **zero** SSRF checks; the probe raises if `assert_url_allowed` is ever called |
| `test_ollama_normalize_base_passes_through_non_http_and_credential_urls` | `normalize_base` performs no scheme/credential/address sanitisation (5 hostile shapes) |
| `test_ai_private_network_allowance_also_grants_cloud_metadata` | AUDIT-4E-1 — the AI layer's type-keyed allowance permits `169.254.169.254` / `100.100.100.200` / `fd00:ec2::254` while the default policy refuses them (probe only; `ssrf.py` untouched) |
| `test_escalation_evidence_carries_the_unredacted_short_key` | AUDIT-4E-8 — a 9-char key survives into the dict persisted as layer-8 `ScanFinding.evidence` |
| `test_decode_access_token_raises_recursionerror_on_a_nested_jwt_header` | AUDIT-SA5-1 — a 27 KB nested-header bearer makes `RecursionError` escape `decode_access_token`'s `except jwt.PyJWTError` (live-confirmed as an unauthenticated 500) |
| `test_fetch_live_catalog_raises_on_a_list_shaped_providers_key` | AUDIT-4E-2 — the documented "Never raises" contract is false; `AttributeError` escapes `fetch_live_catalog` |
| `test_deliver_to_channel_raises_on_a_crlf_site_name` | AUDIT-4D-1 — a CR/LF in a user-controlled `site_name` raises out of `deliver_to_channel`, permanently orphaning the remaining channels with no delivery row |
| `test_alert_html_template_escapes_hostile_site_names` | Positive control — the HTML body is safe (autoescape, no `|safe`, survives premailer) |
| `test_crypto_has_no_key_ring_and_rotation_downgrades_to_keyless` | AUDIT-SA5-3 — no rotation helper exists, and after a key change `_deployments` builds a deployment with **no `api_key`** |

### Regression results (exact commands + counts)

```
$env:WARDRESS_TEST_DATABASE_URL="postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_ai_test"
cd backend

uv run --frozen pytest tests/test_phase_sa5_ai_infra_repros.py -q -p no:cacheprovider
  -> 9 passed in 0.38s   (0 failed, 0 skipped)

uv run --frozen pytest tests/test_phase_sa5_ai_infra_repros.py \
  tests/test_phase4e_ai_supplychain_repros.py tests/test_phase4d_delivery_repros.py \
  tests/test_ai_catalog.py tests/test_ai_migration.py tests/test_llm_keypool.py \
  tests/test_phase16_outbound_fetch.py tests/test_phase5_ratelimit_ssrf.py tests/test_ssrf.py \
  tests/test_phase4_alerting.py tests/test_remediation_claim_race.py tests/test_site_icons.py \
  tests/test_phase4_api.py tests/test_auth.py -q -p no:cacheprovider
  -> 250 passed, 1 warning in 181.01s (0 failed, 0 skipped)
     (the 1 warning is a pre-existing apprise `imghdr` DeprecationWarning)

uv run --frozen ruff check tests/test_phase_sa5_ai_infra_repros.py
  -> All checks passed!            (exit 0)
uv run --frozen ruff format --check tests/test_phase_sa5_ai_infra_repros.py
  -> 1 file already formatted      (exit 0)

$env:DATABASE_URL="postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_ai_test"
uv run --frozen alembic upgrade head  -> exit 0
uv run --frozen alembic check        -> "No new upgrade operations detected"   (exit 0)
```

**Rule 5 status:** no regression. The backend-wide `ruff check` / `ruff format` counts rose during the session (9 → 28 errors, 24 → 26 files) **only** because other concurrent subagents added test files; my file appears in neither list. All 14 pre-existing suites in the batch — including 4E's own 21 repro tests and 4D's 5 — re-ran green.

### Measurement summary (Rule 18 — ≥3 passes with variance)

| Measurement | Passes | Values | Variance |
|---|---|---|---|
| Hung provider, 1 deployment | **6** (2 independent 3-pass runs) | 31.61 / 30.05 / 30.03 / 31.39 / 30.03 / 30.08 s | ≤ 1.58 s |
| Hung provider, 2 keyed deployments | 3 | 60.97 / 60.06 / 60.09 s | ≤ 0.91 s |
| Favicon size-cap memory (32 MiB body) | 1 (deterministic `tracemalloc` peak) | 64.2 MiB traced peak; 65 537 B returned | n/a — single deterministic measurement, not a sample |
| Ollama hostname resolution (live) | 1 | `gaierror -2` | n/a — deterministic |
| SSRF policy matrix (7 targets × 2 flag values) | 1 each | deterministic table | n/a |
| litellm DEBUG log-leak (3 prompt records, 2 response records) | 1 (deterministic capture) | 96 records total, 0 containing the API key | n/a |
| Deployment parity | 27 files | 27 MATCH / 0 DIFF | n/a |

### Scratch probes written (Rule 10 — outside the repo)

All under `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-a\ai-infra\`:

| File | What it does |
|---|---|
| `probe_email_injection.py` | Hostile `site_name` → Jinja/premailer escaping + `EmailMessage` header behaviour (AUDIT-4D-1) |
| `probe_fernet_rotation.py` | Encrypt under key A, swap to key B, exercise every decrypt caller (AUDIT-SA5-3) |
| `probe_litellm_posture.py` | litellm globals, cost-map provenance, egress surface (AUDIT-SA5-2) |
| `probe_litellm_sink.py` | litellm logging/audit-log attribute introspection (AUDIT-SA5-2) |
| `probe_litellm_leak.py` | Drives production `_build_router(...).acompletion` against a fake endpoint with DEBUG logging; counts key/prompt/reply occurrences and scans the CWD for files (AUDIT-SA5-2) |
| `probe_redaction_ssrf_catalog.py` | (A) redaction leak end-to-end, (B) the `/api/show` SSRF reader, (C) models.dev payload trust (AUDIT-4E-1/-2/-8) |
| `probe_site_icons_ssrf.py` | Favicon client-construction capture (AUDIT-4D-3) |
| `probe_site_icons_ssrf2.py` | Hop-by-hop redirect matrix + `tracemalloc` size-cap measurement (AUDIT-4D-3/-4) |
| `probe_ssrf_policy.py` | The 7-target × 2-flag policy matrix (AUDIT-4E-1) |
| `probe_pyjwt.py` | In-process RecursionError escape from `decode_access_token` (AUDIT-SA5-1) |
| `probe_pyjwt_live.py` | Live read-only HTTP probe of the nested-header bearer (AUDIT-SA5-1) |
| `probe_dep_reachability.py` | `uv.lock` reverse deps + uvicorn/h11 header-cap introspection |
| `who_requires.py` | Reverse-dependency + installed-version inventory |
| `probe_hang_budget.py`, `probe_hang_multikey.py` | Copies of 4E's preserved hang probes, path-fixed, re-run for 6 samples (AUDIT-4E-3) |
| `parity.ps1` | `docker cp` + `git hash-object` parity sweep |
| Output logs: `pipaudit.json`, `hang_budget_run2.txt`, `redaction_ssrf_catalog.txt`, `site_icons_ssrf.txt`, `site_icons_ssrf2.txt` | Raw captured output for the measurements above |

None is a pytest and none is part of any suite (Rule 5/10). **No production file was modified (Rule 1). The live stack was used strictly read-only (`docker ps`, `docker inspect`, `docker image inspect`, `docker exec … sh -c`, `docker logs`, `docker cp`); no container was started, stopped, rebuilt or pulled, and no install/uninstall script was run.**

### Open items handed to other phases (not investigated here)

- **`beat` has no `depends_on: db`** (`docker-compose.yml`) — Phase 9 (W1-C) territory; noted because `beat` does need `DATABASE_URL` and does import `worker.db`.
- The 7 `ruff` errors in `backend/tools/run_stress_catalog.py` are in the **Phase 5A** stress harness — Phase 5A will need them clean before its gate can go green; logged here because they are the *first* command of the backend CI job (AUDIT-4E-11).
- The 2 `ruff` errors in `tests/test_phase4_fresh_eyes_finding_repros.py` (I001) and `tests/test_phase4c_api_surface_repros.py` (F401) belong to Audit Phases 4 and 4C's committed test files.
- `frontend/tests/capture-health.test.tsx`'s flake and the frontend verdict/severity colour work are Phase 4F/9 targets; the frontend test gate was deliberately not re-run here.
- Whether the WeasyPrint advisory is graded Critical (Rule 12's mechanical rule) or High (no demonstrated exploitability at today's call shape) is an explicit Phase 10 decision, per 4E's own note; Session A adds no new reachability, so the argument is unchanged.
