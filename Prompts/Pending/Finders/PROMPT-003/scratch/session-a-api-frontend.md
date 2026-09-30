# PROMPT-003 — SESSION A, SUBAGENT 4: API, Auth & Frontend Deep Verification

- **Audit spec**: `PROMPT-003-capture-detection-audit-and-stress-hardening.md` §1 (21 rules), §6.4 (severity rubric)
- **Scope**: Audit Phase 4C (API routers / deps / ratelimit / security / apikeys / audit / schemas / main) + Audit Phase 4F (all of `frontend/src/**`, `frontend/tests/**`) + API/frontend tests under `backend/tests/`
- **Subagent**: SA4 · **Session date**: 2026-09-30 · **Mode**: diagnosis only (Rule 1 — zero production files modified)
- **Environment**: Windows host, Docker stack up (`wardress-app-1` healthy on :8321), disposable Postgres `wardress-test-pg` on 127.0.0.1:5433, dedicated DB `wardress_sa_api_test`

## Method and parity attestation

| Check | Result |
|---|---|
| Container-vs-HEAD parity (Phase-4C protocol: `docker cp` + `git hash-object`) | **10/10 MATCH, 0 mismatches** — `app/main.py`, `deps.py`, `ratelimit.py`, `security.py`, `routers/{sites,auth,users,health,settings}.py`, `schemas.py`. Every live assertion below is HEAD-valid. |
| Live stack usage | **read-only**. No live user, site, API key or channel was created. All reproducible work done over hermetic ASGI transport against `wardress_sa_api_test`. |
| Working tree after all work | `git status --porcelain` shows only 3 untracked files belonging to **other concurrent subagents** (`test_phase_sa3_orchestration_deep.py`, `test_phase_sa5_ai_infra_repros.py`, `test_session_a2_detection_findings.py`). SA4 added **zero** repo files. |
| Rule 18 (repeatability) | Applied to every variance-prone measurement: the 4F-1 delay sweep (13 points + 3 passes at each of 4 boundary candidates = 25 passes), the frontend suite (3 full passes), the backend API suites (2 batched runs), the 4F-3 shape sweep (19 shapes, deterministic). |
| Rule 13 (verify, don't trust) | **Two hypotheses were falsified** and are reported as verified-clean rather than as findings: the Content-Type bypass of `StrictJSONBodyMiddleware`, and the "XSS via the server-side HTML/PDF templates" hypothesis. Eleven such hypotheses are tabulated at the end. |

---

# PART 1 — Phase 4C findings (API surface)

### [DEEPENED] AUDIT-4C-1 — Single-site create answers 503 after the site is committed; the invited retry 409s (reproduced end-to-end at the HTTP layer, with the bulk-import contrast quantified)

- **Original phase:** 4C
- **Severity:** Medium (unchanged) — operator-facing contract dishonesty exactly during the outage scenario the codebase otherwise handles carefully; no data loss, self-heals via 409, but the response actively misleads the retry.
- **Subsystem / file(s):** `backend/app/services.py:164-190` (`_enqueue_or_fail` → `QueueUnavailableError`), `backend/app/tasks.py:43-60` (`_send` → `HTTPException 503`), `backend/app/routers/sites.py:111-136` (`create_site` → `_http_from_service`), contrast `backend/app/routers/imports.py` per-row degradation.
- **Verification method:** live-equivalent HTTP probe over ASGI transport with a dead-broker Celery client (`redis://127.0.0.1:1/0`, `max_retries=2`), driving the real router through `httpx.AsyncClient`. 4C's committed repro only exercised `services.create_site` directly; this run drives `POST /api/sites`.
- **Evidence:**
  ```
  ATTEMPT 1 POST /api/sites -> 503 {"detail":"Task queue is unavailable — try again shortly"}
  ATTEMPT 2 (the retry the 503 invites) -> 409 {"detail":"A site with this URL already exists"}
  GET /api/sites -> 200 site present? True
  ```
  Same dead broker, **same outage, same call site**, through the bulk-import surface:
  ```
  POST /api/sites/bulk-import -> 200
  {"total_rows":2,"created":2,"skipped":0,"errors":0,"results":[
    {"row":2,...,"status":"created",
     "detail":"created — baseline capture could not be enqueued (task queue unavailable);
                use Rebaseline once it is back","site_id":"2b66ebd5-…"},
    {"row":3,...,"status":"created",
     "detail":"created — baseline capture could not be enqueued (task queue unavailable);
                use Rebaseline once it is back","site_id":"e8ecbe06-…"}]}
  GET /api/sites -> names: ['sa4-bulk-b','sa4-bulk-a']
  ```
- **Deeper analysis:** 4C identified the parity gap by code reading. This run produces the **A/B pair on one outage**, which pins the defect precisely: the correct behaviour already exists in the codebase, is already covered by tests, and simply was not applied to the single-create path. The consumer-facing contract is:
  - single create → `503` + "try again shortly" → retry → `409` "already exists" (self-contradicting; the operator must guess that `Rebaseline` is the recovery action)
  - bulk import → `200` + `created` + per-row "use Rebaseline once it is back" (self-consistent; the client already holds the created `site_id`)

  A client written against the bulk-import contract and pointed at single create retries forever and receives a stream of 409s. The API never returns the created site's `id` on the degraded path, so the client cannot even adopt the bulk-import workaround.
- **Cross-subsystem interactions:** the 503 originates in `app/tasks.py::_send`, which is shared by baseline capture, scan-now and remediation enqueue, so the same misleading shape is reachable from `POST /api/sites/{id}/scan-now` and `POST /api/sites/{id}/rebaseline` (both route through `services.trigger_scan_now` / `services.rebaseline_site`). A scan or rebaseline that commits its row and then 503s reproduces the identical trap with a scan/baseline id the client never receives.

### [DEEPENED] AUDIT-4C-2 — `/docs`, `/redoc`, `/docs/oauth2-redirect`, `/openapi.json` are public and outside rate limiting; the schema narrates the SSRF gate and names the endpoints that probe internal networks

- **Original phase:** 4C
- **Severity:** Medium (unchanged, but the highest-value Medium in this file). **Justification against §6.4:** no secret, credential, hostname or example payload is present (proved by exhaustive pattern sweep), so not Critical; but it is a *true disclosure gap against a stated design intent*, not cosmetic — `main.py:225-228` and `docs/configuration.mdx` both describe the surface as locked down, and `/openapi.json` hands an unauthenticated caller the complete route inventory, the complete RBAC role enum, the refresh-cookie name, internal finding/doc references, and a prose map of the outbound-request defenses. §6.4 Medium ("docs/infra drift that could mislead an operator but doesn't cause incorrect system behavior") is the closest honest fit. High was explicitly considered and rejected: nothing is exploitable from the schema alone, and the product already ships its own `docs/api-reference.mdx`.
- **Subsystem / file(s):** `backend/app/main.py:52-57` (FastAPI ctor — `docs_url`/`redoc_url`/`openapi_url` never set), `backend/app/main.py:246` (rate-limit middleware meters only `/api/`), `backend/app/routers/settings.py` (`validate_ai_provider`, `pull_ollama_model` descriptions), `backend/app/routers/auth.py:315-329` (the description that leaks `Finding 1.3` / `deps.py`), `backend/app/routers/health.py:64-67`, `backend/app/routers/sites.py:543-557`.
- **Verification method:** live HTTP probe against `wardress-app-1` + full in-process schema introspection + exhaustive pattern sweep over the 99,585-byte schema.
- **Evidence — live, unauthenticated, no credential:**
  ```
  /api/health            -> 200    bytes=40
  /api/health/live       -> 200    bytes=15
  /api/health/details    -> 401
  /openapi.json          -> 200    bytes=92500
  /docs                  -> 200    bytes=1007
  /redoc                 -> 200    bytes=889
  /docs/oauth2-redirect  -> 200    bytes=3012
  /favicon.ico           -> 200    bytes=506   (SPA fallback -> index.html)
  /api/sites             -> 401
  cache-control: None | server: None    <- no Cache-Control on the schema
  per-IP limiter buckets after 5 doc fetches: None   <- zero rate-limit budget consumed
  ```
- **Evidence — what the schema actually contains (enumerated, not asserted):**
  ```
  paths: 65 | components.schemas: 78 | operations: 85 | in-process bytes: 99,585
  securitySchemes: {'HTTPBearer': {'type':'http','scheme':'bearer'}}
  operations declaring `security`: 81 of 85
      -> the only 4 declared-public are POST /api/auth/login, POST /api/auth/refresh,
         GET /api/health, GET /api/health/live
  ```
  The schema's *security metadata* is accurate — the 4 operations that declare no `security` are exactly the 4 that are genuinely public. The disclosure is entirely in the free-text `description` fields and the schema inventory:

  | # | Disclosed | Where in the schema | Why it matters |
  |---|---|---|---|
  | 1 | **"the effective target URL is SSRF-validated before any request is made"** | `POST /api/settings/ai/ollama/pull` | Names the defense and the attack class. |
  | 2 | **"this makes a live outbound call, so an admin can't spam it to burn provider quota or probe internal endpoints"** | `POST /api/settings/ai/providers/{provider_id}/validate` | Tells an attacker precisely which admin route is an internal-network prober. |
  | 3 | `wardress_refresh` declared as a **cookie parameter** on `POST /api/auth/logout` and `POST /api/auth/refresh` | `parameters[]` | Publishes the refresh cookie's exact name and the route it is scoped to. |
  | 4 | **"Guarded by SessionAuthContext (Finding 1.3) … exactly as deps.py's docstring and the docs promise"** | `POST /api/auth/logout` | Leaks an internal finding ID, an internal source filename, and (by omission) where the guard is *not*. |
  | 5 | **"Backward-compatible with the Phase 0 compose healthcheck, which curls /api/health"** | `GET /api/health` | **Publishes AUDIT-4C-5's stale claim to unauthenticated callers.** The compose healthcheck actually curls `/api/health/live` (`docker-compose.yml:83`). |
  | 6 | `"attempt exactly one SSRF-gated fetch"`, `"Target confidentiality is the default (Phase 27)"`, `"RBAC mirrors the sites-read surface"`, `"rate-limited per user since images load in bursts"` | `GET /api/sites/{site_id}/icon` | Publishes the favicon opt-in posture **and** confirms the double-charge of AUDIT-4C-6. |
  | 7 | Literal prefix **`DEPRECATED`** on `PUT /api/settings/gemini`, `POST /api/settings/gemini/keys`, `DELETE /api/settings/gemini/keys/{key_id}`, `POST /api/settings/gemini/test`, `PUT /api/settings/ollama`, `POST /api/settings/ollama/test` | 6 operations | Advertises that a legacy credential-management surface is still live and admin-writable. |
  | 8 | Full `paths` inventory + `UserRole` enum (`admin`/`analyst`/`viewer`) + `ApiKeyOut.key_prefix` + `HealthDetails.component` names (`database`/`redis`/`worker`) + `AuditLogOut.before_json`/`after_json` + `RemediationActionType` enum | `paths` / `components` | Complete RBAC map, internal-dependency names, and the full persisted data model, free. |

- **Pattern sweep over the whole 99,585-byte schema (negative results matter):**
  ```
  wk_ prefix              0 hits   <- 4C's "wk_ key prefix" example is NOT in the schema
  localhost / 127.0.0.1   0 hits   <- no internal hostnames
  redis:// / postgres://  0 hits
  absolute file paths     0 hits   <- no /data, /app, /tmp
  python package names    0 hits   <- no fastapi/starlette/sqlalchemy/argon2/weasyprint versions
  email literals          1 hit    <- "ops@ex…" — the intentionally-redacted target_hint docstring
  model-name strings     28 hits, all the literal strings "Gemini"/"gemini" (field and route names)
  ```
  **Correction to 4C (partial INVALIDATION):** the `wk_` key prefix is **not** disclosed by the schema. It lives in `app/apikeys.py::generate_api_key` and is visible only to an authenticated key holder via `ApiKeyOut.key_prefix`. 4C's "the `wk_` key prefix" example is **not reproducible** and is withdrawn from the evidence list. The finding stands on items 1–8, which are stronger than the item it replaces.
- **Deeper analysis:** 4C measured *size* (92.5 KB). This run measures *content* and finds the harm is concentrated in 8 prose blocks and 2 cookie parameters, not in the schema bulk. That makes the remedy cheap and precise: shorten or strip the `description=` strings on the outbound-request, auth, health and icon routes, and gate the four doc URLs — neither step requires touching the 78 response models. Separately, **no `Cache-Control` header is set** on `/openapi.json`, so any intermediary or browser cache may retain it; combined with the absence of rate limiting, an anonymous client can pull the full schema at line rate indefinitely with no signal in any log.
- **Cross-subsystem interactions:** items 1–2 name the AI-provider routes whose SSRF posture 4E audited; item 5 makes a 4C docstring drift externally visible; item 6 confirms 4C-6's double-charge is discoverable from the schema; the `HealthDetails` schema names `database`/`redis`/`worker` — the same three components `routers/health.py:231-237` probes, so the schema advertises which infrastructure dependencies exist to attack.

### [CONFIRMED] AUDIT-4C-3 — Two mute implementations with divergent audit snapshots

- **Original phase:** 4C · **Severity:** Low (unchanged)
- **Subsystem / file(s):** `backend/app/routers/sites.py:267-284` (inline mute in `update_site`) vs `backend/app/services.py:519` (`mute_site`; `MUTE_CAP_MINUTES = 7 * 24 * 60` at `:57`).
- **Verification method:** code-trace + repo-wide grep + the committed 4C repro re-run inside the 168-test regression batch (green).
- **Evidence:**
  ```
  backend/app/services.py:57    MUTE_CAP_MINUTES = 7 * 24 * 60
  backend/app/services.py:519   minutes = max(0, min(int(minutes), MUTE_CAP_MINUTES))
  backend/app/schemas.py:86     mute_minutes: int | None = Field(default=None, ge=0, le=7 * 24 * 60)
  ```
  The clamp constant lives in two files with no shared definition, and the audit snapshot shapes differ (`services.mute_site` records `after={**snapshot, "via": via}`; the REST path records `after=site_snapshot(site)` with no `via`).
- **Deeper analysis:** 4C noted the audit-shape drift. This run shows the *clamp itself* is duplicated as a bare literal — `7 * 24 * 60` in `schemas.py:86` versus `MUTE_CAP_MINUTES` in `services.py:57`. The two clamps currently agree so nothing misbehaves, but the REST route's clamp is enforced by a Pydantic bound in a schema file while the service's is enforced by code in another, with nothing tying them. That is exactly the "free-standing copy of a value that lives in another layer" class that AUDIT-2B-5/4F-5 identified in the frontend, on the backend. Both implementations are reachable: REST via `PATCH /api/sites/{id}` with `{"mute_minutes": n}` (analyst-gated), the service via the agent tools and the telegram bot.
- **Cross-subsystem interactions:** a `/mute` from the telegram bot and a mute from the dashboard are therefore distinguishable in the audit log — which is useful for incident review and cannot be relied upon to be consistent.

### [DEEPENED] AUDIT-4C-4 — `DELETE /api/sites/{id}` has no in-flight guard and no cascade disclosure (footprint and guard asymmetry both measured)

- **Original phase:** 4C · **Severity:** Low (unchanged — the destructive action is analyst-gated, audited with a before-snapshot, and artifact files are reaped by the beat janitor)
- **Subsystem / file(s):** `backend/app/routers/sites.py:308-327` (`delete_site` — no guard, `204`, empty body; comment at `:315-316` still says "cleaned by a janitor task in a later phase" although that janitor now exists in `worker/beat_tasks.py`), `backend/app/models.py` FK map (`baselines`, `scans`, `suppression_rules`, `alerts` + `alert_deliveries`, per-site `notification_channels`, `remediation_hooks` + executions, all `ondelete=CASCADE`).
- **Verification method:** HTTP probe over ASGI transport against a seeded site with one row of every child kind, with before/after row counts; plus a three-way in-flight-guard comparison on one identical site state.
- **Evidence — the guard asymmetry, same site state (`capturing` baseline + `running` scan):**
  ```
  POST   /api/sites/{id}/scan-now    -> 409 "inflight has no ready baseline yet — capture a baseline fir…"
  POST   /api/sites/{id}/rebaseline  -> 409 "A baseline capture is already in progress for inflight"
  DELETE /api/sites/{id}             -> 204  body=''  content-length=0
  ```
  Two routes refuse on exactly the state the third silently accepts.
- **Evidence — exact destroyed footprint:**
  ```
  before: Site=1, Baseline=1, SuppressionRule=1, RemediationHook=1, NotificationChannel=1, AuditLog=0
  -> 204, body = '' (0 bytes), no headers beyond the status
  after : Site=0, Baseline=0, SuppressionRule=0, RemediationHook=0, NotificationChannel=0, AuditLog=1
  destroyed: {Site:1, Baseline:1, SuppressionRule:1, RemediationHook:1, NotificationChannel:1}
  ```
  Five distinct row kinds destroyed per call, plus `Scan`, `Alert`, `AlertDelivery` and `RemediationExecution` by the same CASCADE (unseeded here, so zero in the counts). The response discloses **nothing** — not a count, not a warning, not a `Link`/deprecation header.
- **Deeper analysis:** the 0-byte `204` is the sharpest part. Every other destructive-looking surface in this API answers with a body the client can render — `409` with a reason, `422` with a validation list. `DELETE` is the only place where an irreversible multi-table destruction is completely invisible to the caller, so the frontend can neither warn nor confirm. 4C called this "operator surprise"; measured, it is an unauditable-destructive-operation contract gap. The stale janitor comment at `sites.py:315-316` is also still present at HEAD (4C recorded it inside the finding text; it remains uncorrected).
- **Cross-subsystem interactions:** the destroyed suppression rules are the false-positive-suppression config that `worker/detection/suppress.py` depends on; the destroyed remediation hooks are the outbound-webhook registrations `worker/remediation_tasks.py` fires from; the destroyed notification channels are the delivery targets `app/alerting.py` dispatches to. One `DELETE` can simultaneously remove a site's suppression tuning, its auto-remediation wiring, its alert routing, and the baseline its next scan would compare against.

### [CONFIRMED + DEEPENED] AUDIT-4C-5 — Readiness docstring cites a compose healthcheck that no longer exists; the drift is now **public**, and the exact oracle disclosure is measured

- **Original phase:** 4C · **Severity:** Low for the docstring drift (unchanged). The HTTP-status half of this surface is filed separately as **AUDIT-SA4-9** (Medium).
- **Subsystem / file(s):** `backend/app/routers/health.py:6-8` (module docstring repeats the stale claim), `:64-70` (the readiness route; docstring at `:66-67`).
- **Verification method:** code-trace + live `docker inspect` / compose read + in-process schema dump + forced-DB-down probe.
- **Evidence:** `docker-compose.yml:83` healthcheck = `["CMD","curl","-sf","http://localhost:8000/api/health/live"]`. The route docstring and the module docstring both say `/api/health`. Confirmed at HEAD (container-vs-HEAD parity: `routers/health.py` MATCH).
- **Deeper analysis — two things 4C did not have:**
  1. **The stale claim is published to unauthenticated callers.** `GET /api/health`'s `description` string is part of the public `/openapi.json` (AUDIT-4C-2 item 5), so the false statement is no longer merely a code comment — it is an externally published claim about the deployment's healthcheck topology.
  2. **What an unauthenticated caller actually learns (both branches measured):**
     ```
     DB-UP   GET /api/health        -> 200 {"status":"ok","service":"wardress-api"}
     DB-DOWN GET /api/health        -> 200 {"status":"degraded","service":"wardress-api","detail":"database unreachable"}
     DB-DOWN GET /api/health/live   -> 200 {"status":"ok"}
     DB-DOWN GET /api/health/details-> 401
     ```
     The residual note 4C left open is now answered exactly: the disclosure is `{status, service, "database unreachable"}` and nothing more. No stack trace, no DSN, no hostname, no latency — `_db_ok` swallows the exception entirely (`health.py:50-55`). The oracle is therefore **narrower** than a generic "DB oracle" implies (reachability only) but **wider** in one respect 4C did not note: it answers `200` in both branches (AUDIT-SA4-9). 4C's characterisation — "should be a stated decision, not an accident of a stale justification" — remains correct.
- **Cross-subsystem interactions:** `_db_ok` is shared with `health_details` (`health.py:159`), so the authenticated status page inherits the same suppressed-exception behaviour. The schema sweep additionally shows `HealthComponent.detail` is populated with `f"{type(exc).__name__}"` for redis and worker (`health.py:88`, `:120`) — an authenticated-only leak of a Python exception class name, and the only place an internal type name reaches a client in this router.

### [CONFIRMED] AUDIT-4C-6 — Three routes double-charge the per-user rate limit (effective budget measured: 10 → 5)

- **Original phase:** 4C · **Severity:** Low (unchanged)
- **Subsystem / file(s):** `backend/app/deps.py:95-97` (per-user charge in `get_auth_context`) × `backend/app/routers/sites.py:559` (`get_site_icon` calls `enforce_user_rate_limit` again), `backend/app/routers/settings.py` (`validate_ai_provider`, `pull_ollama_model`).
- **Verification method:** behavioural measurement. *Method note (Rule 13):* my first attempt instrumented `app.ratelimit.enforce_user_rate_limit` and recorded **0** charges, because `deps.py` binds the name at import (`from app.ratelimit import enforce_user_rate_limit`) so patching the module attribute does not affect `deps`'s binding. That measurement was **discarded as invalid**; the behavioural result below is the valid one.
- **Evidence (arithmetic confirmed by observation, and against the shipped default):**
  ```
  RATE_LIMIT_PER_USER=10   (production default = 240/min, window 60s)
    GET /api/sites                    -> 200s=10  first429 at request 11
    GET /api/sites/{id}/icon          -> 200s=5   first429 at request 6
  ```
  Extrapolated to the shipped default of 240/min: **`/api/sites/{id}/icon` has an effective budget of 120 requests/minute, not 240** — every favicon load costs two.
- **Deeper analysis:** 4C called the double-charge "undocumented". It is worse than undocumented: the behaviour depends on a **setting that defaults to off**, so the default deployment pays the tax for nothing. `get_site_icon` calls `enforce_user_rate_limit(request, str(user.id))` at `:559` and only *then* `get_favicon_enabled(db)` at `:560` — the charge is levied before the favicon setting is consulted, and a favicon-off deployment (the default) returns `404` with zero outbound work. With the default 240/min budget and favicons off, an operator opening the Sites page with 100 sites issues 100 icon requests costing **200** of their 240/min budget, leaving 40 requests/minute for everything else including the site's own `scan-now`. Combined with the favicon blast radius (one request per component mount, no dedupe — 4F's own opportunity note), this is the most likely source of a *spurious* 429 in normal operation, and it is invisible in every log because 429s are not logged.
- **Cross-subsystem interactions:** `validate_ai_provider` and `pull_ollama_model` double-charge identically, so an admin debugging a provider burns limiter budget on top of provider quota. All three routes' public OpenAPI descriptions announce the per-user limiter (AUDIT-4C-2 item 6), so the double-charge is discoverable from the schema as well as from the code.

### [DEEPENED] AUDIT-4C-7 — `DELETE /api/users/{id}` hard-deletes any non-self user regardless of usage; the "never-used accounts" precondition is not enforced — and the endpoint has no UI caller at all

- **Original phase:** 4C · **Severity:** Low (unchanged; the reachability picture is *better* than 4C recorded)
- **Subsystem / file(s):** `backend/app/routers/users.py:1-8` (module docstring: "Hard delete exists for cleanup of never-used accounts") and `:141-166` (`delete_user` — no usage precondition), `backend/app/models.py` (`api_keys.user_id` CASCADE, `agent_conversations.user_id` CASCADE).
- **Verification method:** HTTP probe with a fully-exercised victim account, plus a repo-wide grep of the client's delete path.
- **Evidence:**
  ```
  victim api-key             -> 201
  victim agent conversation  -> 201 {"id":"169c0c23-…","surface":"web","title":null,…}
  before: RefreshToken=1, ApiKey=1
  DELETE /api/users/{id} -> 204  body=''
  after : RefreshToken=0, ApiKey=0
  destroyed: {RefreshToken: 1, ApiKey: 1}      (+ the agent conversation, CASCADE)
  victim login after delete -> 401
  ```
  The docstring's precondition ("never-used accounts") is violated by construction: the account **had** an API key and an agent conversation, and the delete succeeded silently with an empty body. Reachability from the product:
  ```
  src/components/users-card.tsx:200   apiClient.updateUser(user.id, body)   <- the only mutation
  src/lib/api.ts:1006-1007            export const deleteUser = ...          <- 0 references elsewhere
  ```
- **Deeper analysis:** 4C rated the risk from the API surface. This run establishes that **no dashboard UI can reach this endpoint** — `deleteUser` is one of 12 provably-dead client functions (AUDIT-SA4-10), and `users-card.tsx` only ever calls `updateUser`. That materially lowers real-world blast radius to "hand-crafted API call by an admin", which is why the severity stays Low rather than rising. It also exposes a product gap in the opposite direction: the Users card offers role change, activation and password reset but has **no delete affordance**, so the documented "cleanup of never-used accounts" workflow has no UI path and the docstring's stated purpose is unreachable from the product.
- **Cross-subsystem interactions:** this is the only way an in-scope route reaches an excluded subsystem's data — `app/agent/` conversation history (excluded per §0) is destroyed by this admin call. By contrast `users.py:103-121` correctly revokes refresh tokens on role change and deactivation, and `deps.py:76-78` rejects access tokens for inactive users immediately, so those two paths *are* safe; the **password** path is not (AUDIT-SA4-1).

---

# PART 2 — Phase 4F findings (frontend)

### [DEEPENED] AUDIT-4F-1 — The `capture-health.test.tsx` flake is an implicit 1000 ms assertion budget; the **minimum** triggering delay is measured at exactly 1000 ms and is load-independent

- **Original phase:** 4F (and the AUDIT-2B-5 flake lineage) · **Severity:** Low (unchanged — no product behaviour is affected; the defect is in the verification gate itself)
- **Subsystem / file(s):** `frontend/tests/capture-health.test.tsx:158-162` (the `waitFor` with no explicit timeout); harness default `asyncUtilTimeout = 1000 ms` (`frontend/vite.config.ts:22-25` sets no `test` timeout at all); data path `frontend/src/pages/site-detail.tsx:323-356` (three queries) plus `useArtifact`/`SiteFavicon` fetches.
- **Verification method:** deterministic delay sweep (13 points, 0 ms → 1400 ms) plus 3-pass repeatability at the four boundary candidates = 25 test passes. Scratch instrumentation file, deleted after the run (Rule 10).
- **Evidence:**
  ```
  SA4FLAKE | delay=    0ms | PASS | elapsed=  149ms
  SA4FLAKE | delay=  600ms | PASS | elapsed=  660ms
  SA4FLAKE | delay=  750ms | PASS | elapsed=  799ms
  SA4FLAKE | delay=  850ms | PASS | elapsed=  897ms
  SA4FLAKE | delay=  900ms | PASS | elapsed=  960ms
  SA4FLAKE | delay=  925ms | PASS | elapsed=  968ms
  SA4FLAKE | delay=  950ms | PASS | elapsed=  972ms
  SA4FLAKE | delay=  975ms | PASS | elapsed= 1014ms
  SA4FLAKE | delay= 1000ms | FAIL | elapsed= 1020ms     <- boundary
  SA4FLAKE | delay= 1050ms | FAIL | elapsed= 1017ms
  SA4FLAKE | delay= 1100ms | FAIL | elapsed= 1009ms
  SA4FLAKE | delay= 1200ms | FAIL | elapsed= 1012ms
  SA4FLAKE | delay= 1400ms | FAIL | elapsed= 1010ms

  Rule 18 repeatability (3 passes each):
    900ms  ->  PASS / PASS / PASS
    950ms  ->  PASS / PASS / PASS
    1000ms ->  FAIL / FAIL / FAIL
    1050ms ->  FAIL / FAIL / FAIL
  ```
- **Deeper analysis:** 4F established the mechanism and reported the boundary only coarsely ("≥900 ms fails / 1400 ms reproduces"). This run **pins the minimum triggering delay to the interval 975 ms < d ≤ 1000 ms** and demonstrates that the failure is **not load-sensitive**: the boundary is identical on an idle machine and 3/3 passes land on the same side of it at every candidate. The assertion fires at 1009–1020 ms, matching 4F's independent 1016–1020 ms measurement from a different session — so the two sessions agree to within measurement noise.
  The operational consequence is sharper than "the test is flaky". The binding budget is *not* the render cost (22 ms warm, per 4F) but the total latency of the **five** requests the awaited text depends on, because the page commits it only after all five settle. The flake is therefore a statement about **transport latency**, not CPU. Any environment where the API is >1 s away — a reverse proxy, a VPN, a cold container, an overloaded host, or a first-connection handshake in the `fetch` implementation — reproduces it with **zero** CPU contention. 4F's framing ("any scheduling hiccup pushes the whole path past 1000 ms") understates this: the budget has essentially no head-room at all.
- **Cross-subsystem interactions:** the same three-query data path is the *production* page's path, so the latency budget that is too tight in the test is also the page's real first-paint budget for the Scans tab. Nothing in `src/` bounds it, and no test anywhere in `frontend/tests/` asserts a latency budget.

### [CONFIRMED] AUDIT-4F-2 — A scan whose detection channels went dark renders as Clean / 0% / "0/1 layers ran"; the `degraded` key is dropped by the client and `consecutive_degraded_scans` is read by zero source files

- **Original phase:** 4F · **Severity:** Medium (unchanged — a partial implementation of PROMPT-002 Phase 7's explicit intent, per §6.4 Medium)
- **Subsystem / file(s):** `frontend/src/lib/api.ts:312` (`layer_scores: Record<string, { score: number | null; skipped: boolean }>` — the third key is missing), `frontend/src/lib/api.ts:123` (`api<T>` casts `await resp.json()` straight to `T`), `frontend/src/pages/site-detail.tsx:71-101` (`verdictBadge`/`scanDot`/`riskCell`), `:103-111` (`layerSummary`); backend seams `backend/worker/detection/types.py::degraded_result`, `backend/app/routers/sites.py:70-74` + `:231`, `backend/app/routers/health.py:226`.
- **Verification method:** independent schema-vs-source cross-check of every declared pydantic field against `frontend/src` (4F's committed guard already proves the render side and passes).
- **Evidence — the "zero files" claim re-derived from a different direction:**
  ```
  172 pydantic field names declared in backend/app/schemas.py
  fields with ZERO references anywhere in frontend/src: 3
    captured_at                     refs-in-frontend/tests=0
    consecutive_degraded_scans      refs-in-frontend/tests=9   <- referenced ONLY by 4F's own repro tests
    is_current                      refs-in-frontend/tests=0
  ```
  `consecutive_degraded_scans` appears in 9 places under `frontend/tests/` and in **zero** files under `frontend/src/`. That is exactly 4F's claim, independently confirmed.
- **Deeper analysis:** this run found a **third** copy of the degraded predicate, server-side:
  ```
  backend/app/routers/sites.py:74    return any((entry or {}).get("degraded") for entry in (layer_scores or {}).values())
  backend/app/routers/health.py:226   (entry or {}).get("degraded") for entry in (layer_scores or {}).values()
  ```
  Two verbatim copies, one per router, neither importing the other. They agree today. If either changes, the fleet-level "Degraded Captures (24h)" counter on the Health page and the per-site `consecutive_degraded_scans` streak would silently diverge — which is precisely the operator-visible contradiction that made 4F-2 a finding in the first place, one layer deeper and one step from being able to happen. The duplication is logged as a Low drift item (AUDIT-SA4-13), not folded into 4F-2's severity.
- **Cross-subsystem interactions:** the fused score itself remains honest (`worker/detection/fusion.py` treats a `None` score as uncertainty, never a fake 0.0), and no alert path reads `degraded`, so detection and alerting are unaffected. The blast radius is entirely presentational: an operator drilling into a site sees `Clean` / green dot / `0%` while the fleet counter lists that same site under degraded.

### [DEEPENED] AUDIT-4F-3 — An unexpected 200 shape blanks the whole dashboard: **6 of 19** malformed shapes, at **3 distinct unguarded expressions**, affecting **4 of the 10 routes**

- **Original phase:** 4F · **Severity:** Medium (unchanged — and now *better evidenced* rather than worse: the count and blast radius are both larger, but the impact is identical: a blank screen with no message and no recovery short of a manual reload)
- **Subsystem / file(s):**
  - `frontend/src/pages/site-detail.tsx:338`, `:351` — `query.state.data?.items.some(...)` inside the two `refetchInterval` callbacks
  - `frontend/src/pages/site-detail.tsx:436` — `scans.data?.items.some(...)` at render time
  - `frontend/src/pages/site-detail.tsx:441`, `:443` — `s.name.length` (**the site object, not scans**)
  - `frontend/src/pages/site-detail.tsx:731` + the row renderer — `scans.data.items.map(scan => … scan.status …)`
  - `frontend/src/pages/alerts.tsx:305`, `:307` — `alerts.data?.items.length` / `alerts.data!.items.map`
  - `frontend/src/pages/audit.tsx:492`, `:512`, `:514` — `log.data?.items.length` / `log.data!.items.map`
  - `frontend/src/pages/remediation.tsx:266`, `:268` — `executions.data?.items.length` / `executions.data!.items.map`
  - `frontend/src/lib/api.ts:123` — `return (await resp.json()) as T` (no shape validation anywhere)
  - `frontend/src/App.tsx`, `main.tsx` — no `componentDidCatch` / `getDerivedStateFromError` / `errorElement` (grepped: zero hits, unchanged)
- **Verification method:** a 19-case malformed-payload sweep over jsdom rendering, with `process.on("uncaughtException")` and `process.on("unhandledRejection")` handlers capturing the errors that escape React, so the crash itself is the observation rather than a test failure. Scratch file, deleted after the run.
- **Evidence — the full sweep:**
  | payload shape | outcome | `innerHTML` |
  |---|---|---|
  | `items: null` | **UNCAUGHT** `TypeError: Cannot read properties of null (reading 'some')` | 0 — blank |
  | `items: {}` | **UNCAUGHT** `TypeError: scans.data?.items.some is not a function` | 0 — blank |
  | `items: "x"` | **UNCAUGHT** `TypeError: scans.data?.items.some is not a function` | 0 — blank |
  | `items: [null]` | **UNCAUGHT** `TypeError: Cannot read properties of null (reading 'status')` | 0 — blank |
  | missing `items` (4F-9's shape) | **UNCAUGHT** `TypeError: Cannot read properties of undefined (reading 'some')` | 0 — blank |
  | **site payload `{}` or `[]`** | **UNCAUGHT** `TypeError: Cannot read properties of undefined (reading 'length')` | 0 — blank |
  | site payload `null` | **graceful** — "Site not found. Back to sites" | 597 |
  | `items: []` (control) | renders fully | 13317 |
  | `total: "5"` | renders fully | 13362 |
  | `layer_scores: null` on a row | renders fully | 13362 |
  | `verdict: 123` | renders fully | 13362 |
  | `risk_score` missing | renders fully | 13362 |
  | `risk_score: "high"` | renders fully | 13362 |
  | `flag_threshold` missing on site | renders fully | 13363 |
  | `muted_until: "not-a-date"` | renders fully | 13362 |
  | row `status` missing | renders fully | 13362 |
  | `layer_scores: {layer1_hash: null}` | renders fully | 13362 |
  | `layer_scores: {layer1_hash: {}}` | renders fully | 13362 |

  **6 of 19 shapes (32%) blank the entire SPA.** 1 degrades gracefully. 12 render correctly.
- **Deeper analysis — three things 4F did not have:**
  1. **The defect is not one missing guard.** It is **three distinct unguarded expressions in three different layers**: the observer callbacks, the render-time `some`, and — new — `s.name.length` on the **site** payload at `site-detail.tsx:441/443`. The site-payload case blanks the entire SPA **even when the scans payload is perfectly well-formed**, so 4F-9's repro is not the worst case. A `200 {}` from `GET /api/sites/{id}` — a proxy error page, a truncated body, a future field removal — is sufficient.
  2. **`items: [null]` crashes at a fourth site** — the row renderer reading `scan.status` — which is *not* covered by fixing the `items.some` guard.
  3. **The blast radius is 4 of 10 routes, not 1.** `alerts.tsx`, `audit.tsx` and `remediation.tsx` contain the identical `data?.items.length` / `data!.items.map` pattern; the repo-wide grep finds **six further unguarded `.items` expressions** beyond the two site-detail ones. The optional chain guards the *outer* object, never `items`. The same contract violation therefore blanks Alerts, Audit and Remediation too — and no existing test exercises any of those pages with a malformed payload.
  The remaining 12 shapes render cleanly, including every *type* coercion, so the exposure is specifically a **missing collection key**, not type drift. That narrows the remedy exactly: validate that `items` is an array at the `api()` boundary (or a `paged()` guard), plus one root error boundary.
- **Cross-subsystem interactions:** `api.ts:102-120` retries once on 401 behind a single-flight refresh, so a shape mismatch surfacing *after* a token refresh replays the same malformed body. `sanitizeApiDetail` (`api.ts:35-39`) hardens *error* bodies against internal paths (`Traceback`, `File "`, `/app/`) but does nothing for *success* bodies, which is where the crash lives.

### [DEEPENED] AUDIT-4F-4 — Severity colour is defined **eight** different ways across the capture surfaces (4F counted five), and the vocabulary collides inside a single card

- **Original phase:** 4F · **Severity:** Low (unchanged — the *primary* verdict signals remain threshold-correct and every tone is accompanied by a text label, so no reading is silently inverted for a measured risk)
- **Subsystem / file(s):** all tiers re-located at HEAD:
  | # | site:line | rule |
  |---|---|---|
  | 1 | `src/components/risk-gauge.tsx:18-19` | `risk >= threshold` → red; `risk >= 0.15` → orange (**threshold-aware**) |
  | 2 | `src/components/finding-card.tsx:44-45`, `:52-53` | `>= 0.5` red / `>= 0.15` orange (no threshold input) |
  | 3 | `src/components/finding-card.tsx:599` | fusion bar `>= 0.5` / `>= 0.15` |
  | 4 | `src/components/finding-card.tsx:628` | `signaled = score >= 0.15` |
  | 5 | `src/components/finding-card.tsx:523` | `similarity < 0.5` → **red**, else **green** |
  | 6 | `src/components/finding-card.tsx:549` | `semantic_similarity < 0.5` → red, else **no class at all** (default ink) |
  | 7 | `src/components/finding-card.tsx:344` | signature `weight >= 0.9` strong / `>= 0.5` medium / else weak (**a seventh threshold set**) |
  | 8 | `src/pages/scan-detail.tsx:457`, `:459` | `>= 0.5` / `>= 0.15` |
  | + | `src/pages/site-detail.tsx:91-101` | verdict-driven |
  | + | `src/pages/site-detail.tsx:109` | layer "signaled" at **`> 0.05`** — a factor of **3×** below the 0.15 every other surface uses |
  | + | `src/components/dom-diff-tree.tsx:229/233/237` | green = added, red = removed |
  | + | `src/pages/alerts.tsx:167`, `src/pages/remediation.tsx:161` | unconditional red (AUDIT-4F-8) |
- **Verification method:** code-trace + repo-wide grep; 4F's committed tier-consistency pair re-runs green in the 144-test suite.
- **Evidence:** 4F's contradiction repro still holds — `scoreTone(0.45) === "text-accent-orange"` while `riskTone(0.45, 0.3) === "red"` and `riskTone(0.45, 0.5) === "orange"`: one value, three tones.
- **Deeper analysis:** the count is worse than 4F's five, and the additions are not cosmetic variations of one idea — they are **three semantically different quantities sharing one colour vocabulary**, two of them inside one card:
  - `finding-card.tsx:523` colours a **similarity** (lower = worse) on the same green/red scale as **risk** (higher = worse). The direction is correct *for similarity*, but `text-accent-green` there means "0.51 similar", not "clean" — so one token carries two opposite meanings 200 lines apart in the same file, on the same card that renders the risk tone from tier #2.
  - `finding-card.tsx:549` applies the same `< 0.5 → red` rule to `semantic_similarity` but leaves the `>= 0.5` branch **uncoloured**, so the pair is red-vs-default rather than red-vs-green: an *asymmetric* encoding of a symmetric quantity.
  - `site-detail.tsx:109`'s `> 0.05` "signaled" bar means the same scan is simultaneously "signaled" on the site-detail layer summary (0.06 counts), "not signaled" on the finding card (0.15 required), and "clean" on the fusion bar. **Three surfaces, three bars, one scan.**
  None of these mis-signals a *measured risk* value (4F's justification for Low holds), so the severity is unchanged — but the remedy scope is now eight call sites plus one constants module, not seven.
- **Cross-subsystem interactions:** every one of these tones is fed by `ScanFinding.score` / `Scan.layer_scores` produced by the fusion layer, so a single backend score value is painted three different ways within one drilldown. `dom-diff-tree.tsx`'s green-means-added collides with the app-wide green-means-clean, while `visual-diff-slider.tsx` paints the *same* comparison accent-red for altered regions — so the evidence surfaces disagree about which colour means "added".

### [CONFIRMED] AUDIT-2B-5 → AUDIT-4F-5 — `risk-gauge.tsx:19` still asserts a constant that has moved, and the committed executable guard is real and still passes

- **Original phase:** 2B (prior-history) / 4F (re-verified + guarded) · **Severity:** Low (unchanged)
- **Subsystem / file(s):** `frontend/src/components/risk-gauge.tsx:19` — `if (risk >= 0.15) return "orange" // the scheduler's material-change band`; the material-change band is `MATERIAL_CHANGE_RISK = 0.40` (`backend/app/scanning.py`) and the LLM escalation floor is also 0.40 (`backend/worker/llm_escalation.py`).
- **Verification method:** code-trace + the committed executable guard.
- **Evidence:** the comment is present, unchanged, at HEAD. `frontend/tests/phase4f-capture-surface-repros.test.tsx::AUDIT-4F-5` (two tests: the 0.15-vs-0.40 assertion and the `health.tsx` 60 s vs `DISPATCH_TICK_SECONDS` cross-check) passes as part of the full **22 files / 144 tests / 0 failed, exit 0** run reproduced three times this session. **The guard is real** — it parses both files and fails if either drifts, so AUDIT-2B-5 is genuinely closed into an executable check.
- **Deeper analysis:** the guard's value is confirmed. I add that the frontend now has the *capability* to make the comment moot — a shared `riskTone(value, threshold)` module would delete the literal entirely — which is exactly 4F's stated remedy order (fix the comment, or delete the tier in favour of the threshold-aware helper). The same class was re-confirmed on the detection side by 4F (`worker/detection/fusion.py:40` and `:192` assert 0.35 against the same file's own 0.40 rule-floor table at `:185`); that item is out of my scope and is cross-referenced, not re-derived.
- **Cross-subsystem interactions:** `RiskGauge` is the surface that most directly encodes the backend's material-change decision, so the stale comment sits at the exact boundary where a reader would form a wrong model of *why* a 0.15 reading is orange.

### [CONFIRMED] AUDIT-4F-6 — No bidi isolation and no language marking anywhere in the shell

- **Original phase:** 4F · **Severity:** Low (unchanged — the characters themselves survive intact, so nothing is corrupted or hidden)
- **Subsystem / file(s):** `frontend/index.html:2` (`lang="en"`, no `dir`); `src/pages/site-detail.tsx:463-470`, `src/components/site-avatar.tsx:17`, `src/components/dom-diff-tree.tsx:169-171`, `src/components/finding-card.tsx:68-74`, `src/components/bulk-import-dialog.tsx:243`.
- **Verification method:** repo-wide grep for all three possible mitigations.
- **Evidence:**
  ```
  rg -n 'dir=|<bdi|unicode-bidi' src/ index.html   ->  (no matches)
  ```
  Zero `dir=`, zero `<bdi>`, zero `unicode-bidi` across all 55 `src/` files and `index.html`. Unchanged at HEAD; 4F's committed repro passes.
- **Deeper analysis:** the Tier-C stress catalog explicitly includes deep-RTL sites (`aljazeera.net`, `bbc.com/arabic`, `haaretz.co.il`), and the affected surfaces render **captured page text**, not just the operator-supplied site name — `dom-diff-tree.tsx` (captured text/attrs) and `finding-card.tsx`'s `UrlList` (captured URLs and matched page text). So the exposure is larger than "site names". Because Tier C has not yet run, this is a **latent** presentation defect on exactly the corpus Phases 5A/5B/5C will exercise; the remediation prompt should treat it as a prerequisite for those phases rather than an afterwards item.
- **Cross-subsystem interactions:** the affected strings originate in captured HTML (`worker/artifacts.py`), pass through the detection layers' evidence dictionaries, land in `ScanFinding.evidence`, and are rendered by the frontend — a five-hop chain in which no hop normalises directionality.

### [CONFIRMED] AUDIT-4F-7 — The risk gauge is an unnamed `role="application"` surface with no accessible name or value semantics

- **Original phase:** 4F · **Severity:** Low (unchanged)
- **Subsystem / file(s):** `frontend/src/components/risk-gauge.tsx:38-67` (`RadialBarChart` with no `role="img"`, no `accessibilityLayer`, no `aria-label`), wrapped in `Suspense` at `src/pages/scan-detail.tsx:270-274`.
- **Verification method:** rendered-markup measurement; 4F's committed guard passes.
- **Evidence:** `tests/phase4f-capture-surface-repros.test.tsx::AUDIT-4F-8` passes at HEAD, pinning the measured markup: the `svg` carries `role="application"` with `tabindex="0"` and **no** `aria-label`; there is no `role="img"` and no `[aria-label]` in the subtree; `textContent === "42%Fused risk"`; the word "threshold" never appears.
- **Deeper analysis:** this run adds the a11y context the finding was missing. There are **zero `aria-live` / `role="status"` regions anywhere in `src/`** (AUDIT-SA4-6) — and `RiskGauge` is the component whose *value changes over time* as scans arrive. So the one surface a screen-reader user would most want announced is (a) unnamed, and (b) never announced on change. The number is not hidden (it is ordinary text beside the chart), so what is missing is specifically the *value-versus-threshold* statement and any notification of change. `docs/frontend/components.mdx:17,72` claims the primitives deliver "screen-reader semantics out of the box" — true of Radix, not of the recharts surface layered on top.
- **Cross-subsystem interactions:** the gauge consumes `Scan.risk_score` and `Site.flag_threshold` — the same pair AUDIT-4F-4 shows is toned inconsistently elsewhere — so the missing threshold statement compounds the tone inconsistency rather than being an isolated gap.

### [CONFIRMED] AUDIT-4F-8 — Alert- and remediation-queue risk chips are unconditional accent-red, including the `—` placeholder for an unmeasured risk

- **Original phase:** 4F · **Severity:** Low (unchanged — the mis-signal is in the safe direction, and every chip sits beside its own text label and status badge)
- **Subsystem / file(s):** `frontend/src/pages/alerts.tsx:146` (`riskPct = alert.risk_score != null ? … : "—"`) and `:167` (the chip's `className` is the literal `text-accent-red`); `frontend/src/pages/remediation.tsx:125-126` and `:161` (identical shape).
- **Verification method:** source read at HEAD; 4F's committed guard passes.
- **Evidence:**
  ```
  src/pages/alerts.tsx:167      <span className="… text-accent-red …">{riskPct}</span>
  src/pages/remediation.tsx:161 <span className="… text-accent-red …">{riskPct}</span>
  ```
  No conditional tone, no `? :`, no `scoreTone` call — the class is a literal on the element that renders `{riskPct}`, which may be `—`.
- **Deeper analysis:** unchanged and confirmed. One clarification for the remediation prompt: these are the **only two** places in `src/` that render a risk chip, and both sit on the pages an operator triages under time pressure, so the remedy (route both through the shared tone helper from 4F-4, with a neutral/mute tone for `null`) is a two-line change that also closes half of 4F-4's consolidation work.
- **Cross-subsystem interactions:** the values come from `Alert.risk_score` / `RemediationExecution.risk_score`, populated by `app/alerting.py` and `app/remediation.py`. A `null` there means the scan's fused score was never computed (degraded or failed) — the same "not measured" condition AUDIT-4F-2 is about — and the chip currently renders it in the colour reserved for "actively threatening".

### [CONFIRMED] AUDIT-4F-9 — One site-detail view fetches the same scan list twice on mount and polls it on two independent timers

- **Original phase:** 4F · **Severity:** Low (unchanged — two requests return the same rows with different limits, both are legitimately needed, and no incorrect state was produced in any test or live view)
- **Subsystem / file(s):** `frontend/src/pages/site-detail.tsx:333-343` (`["sites", siteId, "scans", { page }]`, `refetchInterval` 2000), `:346-356` (`["sites", siteId, "scans", "timeline"]`, `refetchInterval` 5000), `:55` (`SCANS_PAGE_SIZE = 20`), `:58` (`TIMELINE_WINDOW = 200`).
- **Verification method:** per-view request census (fresh measurement, independent of 4F's 25-mount call-set log).
- **Evidence:**
  ```
  SA4FETCH | site-detail | total=3 api=3 | /api/sites/site-1
                                            /api/sites/site-1/scans?offset=0&limit=20
                                            /api/sites/site-1/scans?offset=0&limit=200
  ```
  Two requests whose URLs differ **only** in `limit`, issued in the same mount, against the same endpoint, with independent caches and independent poll timers. Confirmed at HEAD.
- **Deeper analysis:** the census also establishes that the *rest* of the app is efficient, which sharpens the fix's value:
  ```
  health       -> 1 request  (/api/health/details)
  alerts       -> 1 request  (/api/alerts?offset=0&limit=25&unacknowledged_only=false)
  audit        -> 1 request  (/api/audit-log?limit=50)
  scan-detail  -> 3 requests (/api/sites/{id}, /api/sites/{id}/scans/{scan_id},
                             /api/sites/{id}/suppression-rules)
  ```
  `site-detail` is the **only** view with a redundant fetch, so 4F's remedy (one `listScans(0, 200)` query with a per-consumer `select`) is a local change needing no cross-view coordination. `TIMELINE_WINDOW = 200` is also an over-fetch independent of the duplication: 200 rows are pulled to render a chart on a page whose table shows 20.
- **Cross-subsystem interactions:** both caches are invalidated together by `invalidateQueries({ queryKey: ["sites", site.id, "scans"] })` (prefix match), so there is no staleness bug — 4F's characterisation is accurate. The cost is a doubled per-view query load plus a theoretical intra-view inconsistency (the table polls at 2 s, the timeline at 5 s, on separate caches, over the same rows).

---

# PART 3 — New findings (SA4)

### [NEW] AUDIT-SA4-1 — A password reset does not invalidate outstanding access tokens and does not revoke the account's API keys

- **Severity:** Medium — §6.4: a partial implementation of the obvious credential-revocation contract. Not High: it needs a prior credential compromise to be useful, and the access-token window is bounded by `ACCESS_TOKEN_TTL` (15 min). Not Low: the API-key half is **unbounded** and defeats the documented recovery action entirely.
- **Subsystem / file(s):** `backend/app/routers/users.py:123-125` (the password branch: `user.password_hash = hash_password(body.password)` then `await _revoke_refresh_tokens(db, user.id)`), `backend/app/deps.py:68-79` (`_user_from_jwt`), `backend/app/deps.py:53-65` (`_user_from_api_key`), `backend/app/config.py:43-48` (TTLs).
- **Verification method:** HTTP probe over ASGI transport — mint a session and an API key for a victim, have an admin reset the password, then replay both credentials.
- **Evidence:**
  ```
  before reset  api-key /me        -> 200
  admin PATCH password             -> 200
  AFTER reset  old access token   -> 200 {"id":"b7146603-…","email":"p-victim@example…"}
  AFTER reset  API key            -> 200 {"id":"b7146603-…","email":"p-victim@example…"}
  AFTER reset  live refresh cookie -> 401 {"detail":"Invalid refresh token"}
  login with OLD password          -> 401
  login with NEW password          -> 200
  ```
  Exactly **one** of the three credential classes is killed: refresh tokens. Access tokens survive (stateless JWT, no `auth_version`), and **API keys survive indefinitely** — `_user_from_api_key` only checks `revoked_at is None` and `user.is_active`, neither of which a password change touches.
- **Deeper analysis:** the asymmetry is visible in the code itself. `users.py:90-101` revokes refresh tokens on *role change* precisely because "role rides in the access token" — the comment even acknowledges that access tokens carry state — yet the *password* branch at `:123-125` applies the same revocation while leaving the API key untouched. There is no "log out everywhere" primitive and no `auth_version` / `token_version` column anywhere in `app/models.py`. `MAX_SESSION_TTL` *is* correctly enforced (`auth.py:67-72`, `:258-262`, verified by reading: the successor inherits `session_started_at` and its expiry is capped), and deleted users' tokens are rejected immediately (`deps.py:55-56`, `:76-78`; measured: login 401 after delete). The `is_active=False` path *does* kill both token classes, because both auth helpers re-read the user row — which makes deactivate-then-reactivate the only working eviction procedure an admin has today.
- **Cross-subsystem interactions:** an API key is the credential designed for unattended scripting (a monitor, a CI job, a cron). A compromised key is exactly the scenario that motivates a password reset, and resetting the password leaves it working — so the incident-response runbook implied by the API is wrong. `DELETE /api/users/{id}` does cascade the key, but that also destroys the account, which is not what an operator resetting a password intends.

### [NEW] AUDIT-SA4-2 — The per-IP rate limiter is fully bypassable by a client-supplied `X-Forwarded-For` under the *documented* reverse-proxy configuration, and IPv6 addresses are not normalised

- **Severity:** Medium — §6.4: a documented hardening control is silently voided under a configuration the project itself instructs operators to use. Not High: no authentication or authorization is bypassed and no data is exposed; two independent controls (the per-account lockout, the 1 MiB body ceiling) remain in front of the expensive paths. Not Low: the configuration is *documented as recommended*, the failure is silent, and it voids the dedicated login limiter as well as the general one.
- **Subsystem / file(s):** `backend/app/ratelimit.py:98-106` (`client_ip` — `forwarded.split(",")[0].strip()`), `:117-121` (`enforce_ip_rate_limit`), `:124-136` (`enforce_login_rate_limit`), `backend/app/config.py:88-91`, `backend/app/main.py:246-253`, `README.md:355`, `docs/configuration.mdx:71`.
- **Verification method:** measurement with `TRUST_PROXY_HEADERS` set both ways, three distinct `X-Forwarded-For` shapes, plus an IPv6 /64 rotation probe. `RATE_LIMIT_PER_IP=5`.
- **Evidence:**
  ```
  --- TRUST_PROXY_HEADERS=false (the default) ---
   rotating XFF            -> [401,401,401,401,401,429,429,429]     <- correctly ignored
   proxy-appended XFF      -> [429,429,429,429,429,429,429,429]
   no XFF (socket peer)    -> [429,429,429,429,429,429,429,429]

  --- TRUST_PROXY_HEADERS=true (the documented reverse-proxy setting) ---
   rotating XFF            -> [401,401,401,401,401,401,401,401]     <- 8/8 allowed: limit fully bypassed
   proxy-appended XFF      -> [401,401,401,401,401,429,429,429]
   no XFF (socket peer)    -> [401,401,401,401,401,429,429,429]

  IPv6:
   client_ip("2001:db8:1234:5678:9abc:def0:1234:5678") -> '2001:db8:1234:5678:9abc:def0:1234:5678'
   6 addresses in one /64   -> [401,401,401,401,401,401]            <- 6/6 allowed: limit fully bypassed
  ```
- **Deeper analysis:** the XFF bug is the classic one — `split(",")[0]` takes the **leftmost** entry, which is the one the *client* supplied, while the standard nginx `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for` **appends** the real peer to the *right*. Behind a completely ordinary nginx, `X-Forwarded-For: 203.0.113.7` becomes `203.0.113.7, <real-ip>` and the limiter buckets on the attacker's chosen value. `README.md:355` and `docs/configuration.mdx:71` both tell operators to set this flag for a reverse-proxy deployment and **neither mentions that the proxy must overwrite rather than append**. The correct behaviour is to take the *rightmost* entry, or better, to walk the list right-to-left and drop the first untrusted hop. The second, config-independent vector: `client_ip` returns the raw peer address with no normalisation, so any holder of an IPv6 /64 gets 2⁶⁴ distinct `ip:` buckets from the socket peer alone — no header needed (measured above).
  What was checked and is **not** a finding: the limiter's storage is an in-process `dict` with no external dependency, so it has **no fail-open mode**; `Dockerfile.app:55` starts uvicorn with a single process (no `--workers`) and `docker-compose.yml` sets no `command:` override, so the "N workers = N× budget" bypass is **not reachable** in the shipped topology; API-key rotation does not reset the budget because the per-user bucket is keyed `f"user:{user_id}"` (`deps.py:97`), and parallel sessions share it too; `Retry-After` is correct (`59` on a 60 s window, from `max(1, int(window.reset_at - now))`).
- **Cross-subsystem interactions:** the same `client_ip()` feeds both the general per-IP limiter and the dedicated `login-ip:` login limiter (`ratelimit.py:130`), so bypassing it removes the 30/min login budget as well. What still bounds credential guessing is the per-account lockout (AUDIT-SA4-3), which converts the exposure from "unlimited login attempts" into "unlimited login attempts against an account that is now permanently locked" — the two defects compound into a worse combination than either alone.

### [NEW] AUDIT-SA4-3 — The per-account login lockout is an unauthenticated, effectively permanent denial of service against any known account address

- **Severity:** Medium — §6.4: an availability defect reachable without any credential, on the control plane, at a cost of 4 requests per hour to the attacker. Not High: it requires knowledge of a target email and is trivially visible in `auth.login_failed` audit rows and the `logger.warning` stream. Not Low: on a single-admin self-hosted deployment, locking the admin account locks the entire product, and the lock **cannot be cleared by the legitimate admin logging in**.
- **Subsystem / file(s):** `backend/app/routers/auth.py:49-51` (`_LOCKOUT_THRESHOLD = 5`, `_LOCKOUT_BASE_SECONDS = 60`, `_LOCKOUT_CAP_SECONDS = 900`), `:89-132` (`_register_failed_attempt`, back-off `min(60 * 2**(count-5), 900)`), `:160-172` (the locked fast-reject), `backend/app/models.py` (`User.failed_login_attempts`, `User.locked_until`).
- **Verification method:** HTTP probe, unauthenticated, against a throwaway account.
- **Evidence:**
  ```
  9 wrong-password attempts (no credential at all) -> [401,401,401,401,401,429,429,429,429]
  correct password while locked                   -> 429  Retry-After: 60
      {"detail":"Too many failed login attempts — try again shortly"}
  victim row: failed_login_attempts=5, locked_until=2026-09-30 03:22:26+00:00
  unknown address after 9 tries                   -> 401 {"detail":"Invalid email or password"}   (never locks)
  ```
- **Deeper analysis:** the back-off is `60 * 2**(count-5)` capped at 900 s, so the *cost to the attacker of holding the lock is one request per 15 minutes* — four per hour keeps a target locked indefinitely, at zero cost, forever. The legitimate admin **cannot break the lock by logging in**: `auth.py:162-172` rejects before password verification, so a correct password yields the same 429 with the same `Retry-After`. Only two things clear it: waiting out the window while the attacker keeps re-tripping it, or an admin action (deactivate/reactivate, or delete) that requires a **second** admin. On a one-admin instance that is a hard outage with no self-service recovery. The design comment at `auth.py:44-48` is deliberate and its stated goal (no mid-lock oracle) is correctly achieved; what is missing is any cap on *total* lockout duration, any operator notification, and any single-admin recovery path.
- **Cross-subsystem interactions:** the only other limiter on this path is the per-IP login budget, which AUDIT-SA4-2 shows is bypassable under the documented proxy configuration and bypassable from a rotating address regardless. There is no alerting on `auth.login_failed` beyond a log line, so a sustained lockout campaign is visible only if someone is reading logs.

### [NEW] AUDIT-SA4-4 — The account lockout is a user-enumeration oracle, defeating the deliberately-added constant-time dummy hash

- **Severity:** Low — information disclosure of account existence to an unauthenticated caller, requiring 6 requests. §6.4 Low rather than Medium because the disclosed fact (which addresses have accounts) has low value in the self-hosted model and no further access follows from it.
- **Subsystem / file(s):** `backend/app/routers/auth.py:38-40` (`_DUMMY_HASH = hash_password("wardress-timing-equalizer")` with the comment *"Constant-cost dummy hash so login timing does not reveal whether an email exists (verify runs either way)"*), `:144-158` (unknown-account path), `:160-172` (locked path), `:89-132` (counter write).
- **Verification method:** side-by-side measurement on a registered and an unregistered address.
- **Evidence:** the same 9-request burst run against both kinds of address:
  ```
  registered   victim@example.com       -> [401,401,401,401,401,429,429,429,429]
  unregistered ghost@example.invalid   -> [401] x9, never 429
  ```
  The `401 → 429` transition after exactly 5 requests is a **perfect** account-existence oracle requiring 6 requests and no timing analysis at all.
- **Deeper analysis:** the timing defense is genuinely well-built — `_DUMMY_HASH` is computed at import, `verify_password` runs on both branches, and an audit row is written on both. It is defeated not by timing but by the **state** the two paths leave behind. A second, subtler leak in the same area: the unknown-account path writes an `auth.login_failed` audit row (`auth.py:147-157`) while the **locked** path explicitly writes *no* audit row (`auth.py:163-166`, "no audit row — the tripping attempt already recorded why"). So an admin reading the audit log sees rows for probes against non-existent addresses and *silence* for probes against a locked real account — the enumeration is observable through a second channel. One remedy closes both: a lockout counter also incremented for unknown addresses, or a fixed-shape 429 for both.
- **Cross-subsystem interactions:** the audit rows are consumed by `routers/audit.py` (admin-only) and by `src/pages/audit.tsx`, so the enumeration is visible to two different audiences through two different channels.

### [NEW] AUDIT-SA4-5 — `CORS_ALLOWED_ORIGINS=*` makes the API reflect **any** origin with `Access-Control-Allow-Credentials: true`, contradicting the "explicitly-configured origins" contract

- **Severity:** Medium — §6.4: the stated intent ("CORS locked to explicitly-configured origins", `main.py:225-228`) is not met for a value the parser accepts. Impact is currently **nil**, which is why this is not High: the only cookie is `SameSite=strict` so it is never sent cross-site, and the bearer token lives in JS module memory (`api.ts:9`) and is never a cookie — which is exactly why every cross-origin mutation probe returns 401. The finding is that the entire remaining protection of the credential model rests on a cookie attribute in a different file, with no assertion, test, or input validation guarding the combination.
- **Subsystem / file(s):** `backend/app/config.py:92-99` (`cors_allowed_origins: str = ""`; `cors_origins()` performs no validation), `backend/app/main.py:225-237` (`allow_credentials=True` with the parsed list), `docs/configuration.mdx`.
- **Verification method:** in-process app with `CORS_ALLOWED_ORIGINS=*`, issuing simple and preflight requests with two attacker origins.
- **Evidence:**
  ```
  CORS_ALLOWED_ORIGINS="*"
  simple GET /api/health/live   Origin: https://evil.test
    -> 200  Access-Control-Allow-Origin: https://evil.test
            Access-Control-Allow-Credentials: true    Vary: Origin
  preflight OPTIONS /api/sites  Origin: https://evil.test
    -> 200  ACAO: https://evil.test   ACAC: true
            Allow-Methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT
            Allow-Headers: authorization,content-type   Max-Age: 600
  (identical results for https://app.example.com)
  ```
- **Deeper analysis:** Starlette reflects the request `Origin` verbatim whenever `allow_all_origins` and `allow_credentials` are both set, so `*` is **not** a no-op wildcard — it means "any origin, with credentials". The default is safe: with `cors_allowed_origins = ""` the CORS middleware is **not registered at all**, which is why the cross-origin probes below return bare 401s with no CORS headers and why preflight `OPTIONS /api/sites` is answered by the router as `405 Method Not Allowed`. The gap is that `cors_origins()` validates nothing and neither `README.md` nor `docs/configuration.mdx` warns that `*` is the maximally-permissive value rather than the permissive-but-safe one. Preflights *are* metered by the per-IP limiter (they hit `/api/`), so the only consequence is that they cannot be used to *evade* the limiter.
- **Cross-subsystem interactions:** `docs/configuration.mdx` documents `CORS_ALLOWED_ORIGINS` for hosting the frontend separately; an operator following that guidance and reaching for `*` — a very common first attempt — silently converts the deployment from "no cross-origin access at all" to "any origin may read authenticated responses", removing the defence-in-depth that the SameSite cookie and the in-memory bearer currently provide. No test asserts the safe default or rejects `*`.

### [NEW] AUDIT-SA4-6 — Zero `aria-live` / `role="status"` regions anywhere in `src/`: polling state changes are never announced

- **Severity:** Low — a genuine accessibility defect on the surface whose entire purpose is asynchronous state change, but it degrades gracefully (the user can re-navigate or refresh) and affects assistive-technology users only. §6.4 Low rather than Medium because there is no documented a11y spec requirement being violated: `docs/frontend/components.mdx:17,72` claims Radix provides "accessible focus management, keyboard navigation, and screen-reader semantics out of the box", which is true of the primitives but does not commit to live-region announcements.
- **Subsystem / file(s):** the polling sites `src/pages/site-detail.tsx:323-356` (2 s and 5 s intervals), `src/pages/health.tsx`, `src/pages/alerts.tsx`, `src/pages/remediation.tsx`, `src/pages/scan-detail.tsx:193` — plus the absence of any boundary in `App.tsx` / `main.tsx`.
- **Verification method:** repo-wide grep for every live-region mechanism.
- **Evidence:**
  ```
  rg -n 'aria-live' src/                                  -> (no matches)
  rg -n 'role="status"|role="alert"' src/
    src/pages/sites.tsx:210                  <p role="alert">   <- form error
    src/pages/settings.tsx:1049              <p role="alert">   <- form error
    src/components/api-keys-card.tsx:129     <p role="alert">   <- form error
    src/pages/login.tsx:93                   <p role="alert">   <- form error
    src/components/bulk-import-dialog.tsx:215 <p role="alert">  <- form error
    src/components/remediation-hooks-panel.tsx:393 <p role="alert"> <- form error
    src/components/users-card.tsx:361        <p role="alert">   <- form error
  ```
  Seven `role="alert"` regions exist and **all seven are form-validation messages**. There is not one live region, `aria-live`, `aria-atomic`, or `role="status"` in the application.
- **Deeper analysis:** the badge/dot/risk values that change under the operator's feet while they watch — `verdictBadge`/`scanDot`/`riskCell` (`site-detail.tsx:71-101`), `RiskGauge`, the Health page's degraded counters and capture-quality buckets, the Alerts page's unacknowledged count — are all updated in place with no announcement. A screen-reader user has **no way to learn** that a monitored site went from `Running` to `Flagged`, or that a new alert arrived, without manually re-reading the region. This compounds three other findings: AUDIT-4F-7 (the value-changing surface is unnamed), AUDIT-4F-2 (a dark channel is announced as `Clean`), and AUDIT-4F-8 (an unmeasured risk is announced in the threatening colour) — all states a live region would need to phrase carefully, and none of which the app phrases at all.
- **Cross-subsystem interactions:** the values originate from `Scan.status` / `Scan.verdict` / `Scan.risk_score`, produced by the orchestration and fusion layers and surfaced by `routers/sites.py` and `routers/health.py`. The backend has no push channel (the SPA polls), so the announcement burden falls entirely on the client — meaning any fix is frontend-only and requires no API change.

### [NEW] AUDIT-SA4-7 — Keyboard users cannot use the bulk-import CSV control; three `<Label>` elements label nothing, and no data table in the app has a caption

- **Severity:** Low — an accessibility defect with a workaround (the sitemap-URL import mode is fully keyboard-operable), so it blocks one workflow for one input modality rather than the whole surface.
- **Subsystem / file(s):** `frontend/src/components/bulk-import-dialog.tsx:161-176`; `frontend/src/components/ai-settings-card.tsx:343` and `:457`; `frontend/src/components/ui/table.tsx:97-118` (`TableCaption`, exported and never used).
- **Verification method:** source read + repo-wide grep for the primitive's usages and for `<Label>` without `htmlFor`.
- **Evidence:**
  ```
  bulk-import-dialog.tsx:161   <Label>CSV file</Label>
  bulk-import-dialog.tsx:162-175  <div onDragOver onDragLeave onDrop onClick className="… cursor-pointer …">
  bulk-import-dialog.tsx:176     <input ref={fileRef} type="file" accept=".csv,…" className="hidden" />
      -> no role=, no tabIndex, no onKeyDown on the div;
         the input is display:none (Tailwind `hidden`), therefore unfocusable

  rg -n '<Label>' src/
    src/components/ai-settings-card.tsx:343   <Label>Ollama Mode</Label>   (group heading for 2 <button>s)
    src/components/ai-settings-card.tsx:457   <Label>Auto-Assign Tasks for {modelId}</Label> (group heading for 2 checkbox <label>s)
    src/components/bulk-import-dialog.tsx:161 <Label>CSV file</Label>       (group heading for the drop div)

  rg -n 'TableCaption' src/     -> src/components/ui/table.tsx only (defined + exported; zero call sites)
  rg -n 'scope=|<caption' src/  -> (no matches)
  ```
- **Deeper analysis:** the drop zone is the *only* CSV file picker. Its click handler is on a `<div>` with no role, no `tabIndex` and no key handler, and the `<input type="file">` it proxies to is `display:none` and therefore unfocusable — so a keyboard-only analyst cannot open the file dialog at all. To be precise about terminology: this is *not* a keyboard *trap* (the surrounding Radix `Dialog` correctly traps focus and handles Escape); it is the **absence** of any focusable affordance. The custom listbox menus were checked and are **sound** — all four implement `Escape` at window level returning focus to the trigger, and the shared `src/lib/listbox-keys.ts` model returns `dismiss` on `Tab` specifically so focus is *not* yanked back; that design choice is documented in the lib's own header comment. Separately, three `<label>` elements are used as group headings with no associated control, so a screen reader announces an orphan label; and although the design system *ships* a `TableCaption` primitive, no page uses it, so none of the app's data tables (scans, alerts, audit, remediation, diff trees) has an accessible name and no header cell carries `scope`.
- **Cross-subsystem interactions:** the bulk-import dialog is the front door to the 500-row `POST /api/sites/bulk-import` path measured in AUDIT-SA4-8, so the accessibility gap sits directly on the highest-volume site-creation route. `TableCaption`'s non-use is the same drift class as AUDIT-2B-5/4F-5: a primitive built for a rule the call sites never adopted.

### [NEW] AUDIT-SA4-8 — `GET /api/sites` is unbounded and silently ignores `limit`/`offset`: 600 sites = 364,581 bytes in one response

- **Severity:** Medium — §6.4: measured unbounded growth under a data volume reachable through the product's own API (bulk import admits 500 rows per call), with a client that parses the whole payload on every visit. Not High: a single response, bounded by the site's own row count, on a self-hosted LAN deployment. Not Low: the payload is already in the hundreds of KB and grows linearly with no ceiling.
- **Subsystem / file(s):** `backend/app/routers/sites.py:139-206` (`list_sites` — no `offset`/`limit` parameters at all), `backend/app/routers/imports.py` (`BULK_IMPORT_MAX_CSV_CHARS`, 500-row class), `frontend/src/pages/sites.tsx` (fetches the full array), `frontend/src/lib/api.ts` (`listSites`).
- **Verification method:** seeded 600 sites each with one current baseline, then measured the response and the parameter handling.
- **Evidence:**
  ```
  seeded 600 sites x 1 baseline
  GET /api/sites                      -> 200  items=600  bytes=364581
  GET /api/sites?limit=1&offset=9999  -> 200  items=600  bytes=364581   <- parameters ignored entirely
  GET /api/audit-log (bounded, le=200)-> 200  items=1    total=1    bytes=382
  ```
- **Deeper analysis:** this promotes Phase 2B's "open-by-design residual: unbounded site-list (no pagination)" from a note to a **measurement**. Three points: (1) the response is a bare JSON **array**, so it carries no `total` for a client to paginate against even if it wanted to; (2) `limit`/`offset` are accepted **silently and discarded** rather than rejected, so a client that tries to be polite gets the full list with no error and no indication; (3) this is the endpoint behind the dashboard's **landing route**. For contrast, every endpoint that *declares* pagination is correctly bounded and I could not break any of them:
  ```
  /api/audit-log, /api/alerts, /api/remediation/executions, /api/sites/{id}/scans
    offset=-1           -> 422 greater_than_equal
    limit=0             -> 422 greater_than_equal
    limit=201           -> 422 less_than_equal
    limit=1000000       -> 422 less_than_equal
    offset=99999999999  -> 200 items=[]    (past the end: empty page, correct)
    offset=abc          -> 422 int_parsing
    offset=1.5          -> 422 int_parsing
    limit=-5            -> 422 greater_than_equal
  ```
  The other endpoints that return bare arrays also accept and ignore `limit`/`offset`: `/api/users`, `/api/notification-channels`, `/api/api-keys`, `/api/settings/ai/providers`, `/api/settings/ai/assignments`, `/api/settings/ai/catalog/providers`, `/api/settings/ai/catalog/models`. All are naturally small (the AI catalog is bounded by the bundled `models_dev_catalog.json`) except the site list.
- **Cross-subsystem interactions:** the sites page is where the operator lands first, so the 356 KB payload is fetched on every visit and after every navigation; it is also the payload the favicon blast radius multiplies (one `/icon` request per row, no dedupe — 4F's own opportunity note), so 600 sites means 600 additional icon requests on one page view, each costing **two** of the per-user budget (AUDIT-4C-6).

### [NEW] AUDIT-SA4-9 — `GET /api/health` returns HTTP **200** in both the healthy and the database-down branch, so status-code-based probes report healthy through a total DB outage

- **Severity:** Medium — §6.4: "a docs/infra drift that could mislead an operator but doesn't cause incorrect system behavior" is the Medium band's exact wording, and this is precisely that. Not High: it does not cause incorrect *system* behaviour and the response body does carry `"status":"degraded"`.
- **Subsystem / file(s):** `backend/app/routers/health.py:64-70` (the readiness route — both branches return a dict, and FastAPI serialises both as `200`).
- **Verification method:** forced the DB down by overriding the session dependency to raise, then compared the two branches.
- **Evidence:**
  ```
  DB-UP   GET /api/health        -> 200 {"status":"ok","service":"wardress-api"}
  DB-DOWN GET /api/health        -> 200 {"status":"degraded","service":"wardress-api","detail":"database unreachable"}
  DB-DOWN GET /api/health/live   -> 200 {"status":"ok"}
  ```
- **Deeper analysis:** the route is named *readiness*, and readiness is exactly what a status-code consumer is asking. `curl -sf`, `requests.raise_for_status()`, Docker's `HEALTHCHECK`, Kubernetes probes, and every uptime monitor in the ecosystem branch on the status code — all of them see `200` while the API cannot serve a single authenticated request. The response is correct only for a consumer that parses the body. There is a pleasing irony here: `docker-compose.yml:83` uses `curl -sf .../api/health/live`, and the `live` route deliberately does not touch the DB, so the shipped compose healthcheck is **correct** here; but `health.py`'s docstring claims that same compose healthcheck consumes `/api/health` (AUDIT-4C-5), and *if* that stale claim were ever acted on, the deployment's own healthcheck would go green during a DB outage. The two routes also disagree about severity for the same event: `health_details` computes `overall = "down"` for the identical condition (`health.py:242-246`).
- **Cross-subsystem interactions:** the authenticated status page (`GET /api/health/details`) is the one that correctly reports `down`; the unauthenticated one does not. So the operator with a session sees the outage, and every external monitor does not.

### [NEW] AUDIT-SA4-10 — Twelve provably-dead client functions in `src/lib/api.ts` leave eleven admin routes as live write surfaces with no caller, several advertised as `DEPRECATED` in the public schema

- **Severity:** Low — §6.4 Low (unused stored/API surface, no incorrect behaviour). The one part with teeth is in the cross-subsystem note.
- **Subsystem / file(s):** `frontend/src/lib/api.ts` (12 exports), `backend/app/routers/settings.py`, `backend/app/routers/users.py` (the corresponding routes).
- **Verification method:** repo-wide grep (excluding `node_modules`, `dist`, `Prompts`, `landing`, `walkthrough`) counting every occurrence of each symbol.
- **Evidence — each symbol has exactly ONE occurrence repo-wide, its own definition line:**
  ```
  getGeminiSettings   1   putGeminiSettings  1   addGeminiKey       1   removeGeminiKey    1
  testGemini          1   getOllamaSettings  1   putOllamaSettings  1   testOllama         1
  listCatalogModels   1   updateAiProvider   1   validateAiProvider 1   deleteUser         1
  ```
  And the corresponding backend routes exist, are admin-gated, are **write-capable**, and appear in the public OpenAPI schema:
  ```
  GET/PUT /api/settings/gemini · POST /api/settings/gemini/keys · DELETE /api/settings/gemini/keys/{id}
  POST /api/settings/gemini/test · GET/PUT /api/settings/ollama · POST /api/settings/ollama/test
  GET /api/settings/ai/catalog/models · PATCH /api/settings/ai/providers/{id}
  POST /api/settings/ai/providers/{id}/validate · DELETE /api/users/{id}
  ```
  Of these, **six carry the literal description prefix `"DEPRECATED …"` in the public schema.**
- **Deeper analysis:** two consequences beyond tidiness. First, `POST /api/settings/ai/providers/{id}/validate` — the endpoint whose *public description* reads "this makes a live outbound call, so an admin can't spam it to burn provider quota or probe internal endpoints" (AUDIT-4C-2 item 2) — **has no UI caller at all**. It is reachable only by a hand-crafted request, so the schema's own threat model and the route's actual reachability diverge. Second, `updateAiProvider` being dead is a **functional gap**, not merely dead code: there is no UI path to edit an existing AI provider's label, keys, base URL or model assignment, so an operator who mistypes a base URL must delete and recreate the provider. `listCatalogModels` being dead means the searchable model list (`?provider_id=`, `?tools_only=`) is unreachable from the settings UI, which matches what `ai-settings-card.tsx:438` asks for ("Model ID (Paste)").
- **Cross-subsystem interactions:** this materially lowers AUDIT-4C-7's reachability (no UI can call `DELETE /api/users/{id}`), and it means `app/ai_migration.py:11`'s comment — "`/api/settings/gemini` adapters read/write the new tables" — describes a live compatibility path that **no client exercises**, so its correctness is unverified by the frontend suite and by 4E's AI work.

### [NEW] AUDIT-SA4-11 — The initial JS payload is 1,077 kB / 404 kB gzip, of which 205 kB is inlined provider logos and 146 kB is Markdown machinery for 2 of 10 routes; a route-level `lazy()` split measures 268 kB / 83 kB gzip

- **Severity:** Low — §6.4 reserves High for "a measured performance bottleneck making the system impractical at realistic scale", which this is **not**: 404 kB gzip on a self-hosted LAN dashboard is acceptable. The finding is that the cost is *precisely measured*, entirely avoidable, and currently invisible (Vite's only signal is a generic ">500 kB chunk" warning).
- **Subsystem / file(s):** `frontend/src/App.tsx:6-15` (all 10 pages statically imported), `frontend/src/lib/provider-logos.ts` (161 static asset imports → 146 logos emitted, 107 inlined as base64 data URIs), `frontend/src/components/markdown-message.tsx:1-2` (`react-markdown` + `remark-gfm`, imported by `assistant.tsx:30` and `scan-detail.tsx:26`), `frontend/dist/index.html` (a single `<script type="module">`, no `modulepreload`).
- **Verification method:** measurement — `pnpm build` at HEAD; then a sourcemap-VLQ byte attribution of the eager chunk; then a **controlled experiment**: a full copy of `frontend/` outside the repo (with `node_modules` junctioned, not modified) in which only `App.tsx` was rewritten to `React.lazy` the 9 non-default routes, rebuilt with the identical toolchain.
- **Evidence — build output at HEAD (`dist/index.html` loads exactly one script, no modulepreload):**
  ```
  dist/assets/index-BH4_Nm0m.js            1,103.50 kB │ gzip: 417.54 kB   <- eager, single chunk
  dist/assets/CategoricalChart-CARV6m3D.js   254.53 kB │ gzip:  78.65 kB   <- recharts, already lazy
  dist/assets/incident-timeline-*.js         103.92 kB │ gzip:  26.43 kB   <- already lazy
  dist/assets/risk-gauge-*.js                 29.82 kB │ gzip:   9.01 kB   <- already lazy
  dist/assets/index-*.css                    104.48 kB │ gzip:  29.35 kB
  fonts: 20 files, 400.4 kB | img/svg: 9 files, 61.6 kB
  ```
  **Byte attribution of the eager chunk** (sourcemap VLQ decode, 1,077.4 kB attributed; cross-checked by direct regex on the emitted file):
  ```
  node_modules                                511.2 kB  47.5%
  src/assets/providers/* (inlined logos)      242.3 kB  22.5%
  src/pages/*                                 183.0 kB  17.0%
  src/components/*                             99.4 kB   9.2%
  src/lib/*                                    36.4 kB   3.4%
  top packages: react-dom 174.4, react-router 39.1, @tanstack/query-core 32.0,
                sonner 31.8, micromark-core-commonmark 26.7, tailwind-merge 26.5
  top page sources: settings.tsx 45.1 kB, health.tsx 37.6 kB, audit.tsx 19.4 kB, …
  ```
  **Direct, sourcemap-independent cross-check of the inlining claim:**
  ```
  index-BH4_Nm0m.js             size=1077.4kB gzip=404.4kB dataURIs=107 dataURI bytes=205.5kB (19.1%)
  index-l0F46u4x.js (variant)   size= 268.5kB gzip= 83.4kB dataURIs=  0 dataURI bytes=  0.0kB
  settings-C3OQuBbe.js (variant) size= 348.0kB gzip=192.9kB dataURIs=107 dataURI bytes=205.5kB
  markdown-message-*.js (variant)size= 152.3kB gzip= 44.7kB dataURIs=  0 dataURI bytes=  0.0kB
  ```
  **The controlled experiment (route-level `React.lazy`, nothing else changed):**
  ```
  eager index chunk:  1,077.4 kB / 404.4 kB gzip  ->  268.5 kB /  83.4 kB gzip
                      -808.9 kB (-75.1% raw)          -321.0 kB (-79.4% gzip)
  new deferred chunks (variant build):
    settings-C3OQuBbe.js          356.44 kB / 198.05 kB gzip   (contains all 107 logo data URIs)
    CategoricalChart-1YI25ioe.js  254.57 kB /  78.67 kB gzip   (recharts — already deferred at HEAD)
    markdown-message-DqaVTTgK.js  155.95 kB /  46.36 kB gzip   (react-markdown + remark-gfm — was eager at HEAD)
    incident-timeline-*.js        103.95 kB /  26.44 kB gzip
    api-*.js                       56.23 kB /  18.60 kB gzip
    site-detail / scan-detail / health / audit / alerts / assistant / remediation
      43.9 / 41.4 / 41.5 / 20.6 / 16.4 / 15.7 / 12.8 kB
    risk-gauge-*.js                 29.82 kB /   9.01 kB gzip
  ```
- **Deeper analysis:** three distinct inefficiencies are now separated and quantified rather than lumped together as "the bundle is big".
  1. **No route-level code splitting at all.** `App.tsx` statically imports 10 pages, so the login page — the only thing an unauthenticated visitor ever sees — downloads every page. `recharts` was correctly split already (4F noted the lazy gauge and timeline); nothing else was.
  2. **205 kB of base64 provider logos in the initial JS.** `provider-logos.ts` statically imports 161 logo assets; those under Vite's 4 KiB inline limit become literal `data:` strings in the chunk. They are only ever displayed on the AI Settings page. Moving them behind a dynamic `import()` map, or raising `assetsInlineLimit` for them, removes 19% of the initial payload *independently of any route splitting*.
  3. **146 kB of Markdown machinery for 2 of 10 routes.** `react-markdown` + `remark-gfm` and their whole `unified`/`remark`/`rehype`/`micromark`/`mdast` chain (26 packages in the top-12 alone) exist solely to render assistant messages and scan explanations. The variant build isolates them as a 155.95 kB chunk loaded only on those two routes.
  Total JS bytes *grew* slightly in the variant (4 chunks / 1,457 kB → 31 chunks / ~1,653 kB) purely from chunk-boundary overhead, which is the expected trade and invisible on the wire because only the eager chunk is fetched. There is also a UX cost that must be weighed: every route becomes a Suspense boundary, so the remedy needs a deliberate fallback rather than `null`.
- **Cross-subsystem interactions:** the per-view request census shows `site-detail` is the only view with a redundant fetch (AUDIT-4F-9), so the bundle problem is entirely a **delivery** problem, independent of the API surface. Nothing in `frontend/tests/` asserts a bundle-size or chunking budget, and CI has no such gate, so there is no standing guard against re-monolithisation.

### [NEW] AUDIT-SA4-12 — The audit-log `actor` filter treats `%` and `_` as LIKE wildcards, so a literal search silently over-matches

- **Severity:** Low — §6.4 Low: an admin-only read filter whose worst case is extra rows in a results list. No write, no authz, no exposure.
- **Subsystem / file(s):** `backend/app/routers/audit.py:38-39` — `query = query.where(AuditLog.actor_email.ilike(f"%{actor}%"))` with no escaping of the interpolated value.
- **Verification method:** seeded three known addresses and queried with literal and wildcard forms.
- **Evidence:**
  ```
  actor='alice@example.com'  total=1  matched=['alice@example.com']
  actor='alice%example.com'  total=2  matched=['alice@example.com','aliceXexample.com']  <- % acted as a wildcard
  actor='alice_example.com'  total=2  matched=['alice@example.com','aliceXexample.com']  <- _ acted as a wildcard
  actor='a'                  total=4  matched=[... all four ...]
  actor='%'                  total=4  matched=[... all four ...]
  ```
- **Deeper analysis:** this was logged by 4C as an **Idea** ("escape LIKE metacharacters in the audit-log `actor` filter"), not as a finding; this run supplies the missing counter-example. Searching for a literal address that happens to contain `%` or `_` returns rows for **different** addresses, and `%` alone is a match-everything. Realistic impact on an incident review: an admin searching for a specific actor can be handed another actor's rows and read them as evidence. The remedy is one `escape_like` call, or an explicit "contains" mode plus an exact-match option. Note `action` uses `startswith` (`:34-35`) rather than LIKE and `target_type` uses `==` (`:36-37`), so neither is affected — `actor` is the only interpolated pattern on the route.
- **Cross-subsystem interactions:** the filter feeds `GET /api/audit-log`, which `src/pages/audit.tsx:428` ("Filter by target type") and `:471` (the actor input) render directly — so the over-match reaches the operator as extra rows rather than as an error, with nothing on screen indicating that a wildcard was interpreted.

### [NEW] AUDIT-SA4-13 — Four dead symbols and one duplicated predicate: the JWT `role` claim, `AnyRoleUser`, `TableCaption`, two unused response fields, and the degraded predicate copied into two routers

- **Severity:** Low — §6.4 Low: cosmetic/dead surface. The security-relevant corollary (demotion is immediate) is a **positive** verified property, recorded below.
- **Subsystem / file(s):** `backend/app/security.py:41-51` (`create_access_token` embeds `role`), `backend/app/deps.py:126-132` (`AnyRoleUser`), `backend/app/routers/health.py:226` vs `backend/app/routers/sites.py:70-74`, `frontend/src/components/ui/table.tsx:97-118` (`TableCaption`), `backend/app/schemas.py` (`BaselineOut.captured_at`, `BaselineOut.is_current`), `backend/app/schemas.py:86` vs `backend/app/services.py:57`.
- **Verification method:** repo-wide grep for each symbol, plus a behavioural check of the role-demotion path.
- **Evidence:**
  ```
  payload["role"]            -> 1 hit, and it is a TEST ASSERTION (tests/test_security.py:42)
  payload.get("role")        -> 0 hits
  AnyRoleUser                -> 1 hit (backend/app/deps.py:128, its own definition)
  TableCaption               -> defined + exported in ui/table.tsx; zero call sites
  get("degraded") predicate  -> verbatim duplicate at routers/health.py:226 and routers/sites.py:74
  BaselineOut.captured_at    -> 0 references in frontend/src (and 0 in frontend/tests)
  BaselineOut.is_current     -> 0 references in frontend/src (and 0 in frontend/tests)
  model columns never read outside models.py -> 0 (the single regex hit, `refresh_tokens`, is a
                                                relationship(), not a column)
  frontend components never imported          -> 0
  ```
- **Deeper analysis:** the `role` claim is the interesting one, and it cuts both ways.
  **Dead:** it is written into every access token and read by nothing in production code — `deps.require_roles` (`deps.py:114-121`) reads `user.role` from a **fresh database read** on every request.
  **Good:** that is exactly why a role demotion takes effect **immediately** rather than after `ACCESS_TOKEN_TTL`. Measured:
  ```
  before demotion  viewer GET /api/users              -> 200
  demote admin -> viewer                              -> 200
  AFTER demotion  SAME access token GET /api/users    -> 403
  AFTER demotion  SAME token POST /api/users          -> 403 "This action requires the admin role"
  ```
  So a reader of `deps.py` could reasonably conclude that the token's `role` claim is authoritative and that revocation is needed on demotion. It is not — and `users.py:99-100`'s comment ("Role rides in the access token; cut sessions so the change takes effect at the next refresh, not in 15 minutes maybe") describes a mechanism **stronger than its author believed**: the role is re-read from the DB, so the refresh revocation is belt-and-braces rather than the enforcement point. That comment is therefore itself drift, and it is the same "comment asserts a mechanism that has moved" class as AUDIT-2B-5/4F-5 — on the backend, and in the opposite direction (the code is safer than the comment claims). The duplicate degraded predicate and the two unused response fields are ordinary drift risk.
- **Cross-subsystem interactions:** the DB-read-on-every-request design that makes the `role` claim dead is the same mechanism that makes AUDIT-SA4-1's access-token-survives-password-reset possible: with no token-version check, a stateless token can only be invalidated by a property of the *user row* (`is_active`). Deactivating is the only immediate kill switch, which is precisely why `users.py:104-107` blocks self-deactivation.

---

# PART 4 — Verified-clean, and the four mandatory closing sections

## Verified-clean (Rule 13 in both directions — hypotheses tested and falsified)

These were investigated with the same rigour as the findings above and **did not reproduce**. Recording them prevents later phases from re-deriving them.

| # | Hypothesis | Method | Result |
|---|---|---|---|
| V1 | A wrong/absent `Content-Type` bypasses `StrictJSONBodyMiddleware` and re-opens the NaN/Infinity → 500 class it exists to kill | 5 content types × 3 malformed bodies on `POST /api/auth/login`, then on `/api/users` | **Falsified.** All 15 combinations → `422`. With `application/json` the middleware answers `{"detail":"Request body is not valid JSON"}`; with `text/plain`, `application/x-www-form-urlencoded`, or no content-type, FastAPI itself never json-decodes the body (it decodes only `application/*` or an absent content-type) and pydantic rejects with `model_attributes_type`. **Content-Type validation is effectively enforced** — just by FastAPI rather than by this codebase. |
| V2 | The body-size ceiling only covers some paths | 2 MB bodies on 7 method/path pairs, plus a 10 MB **chunked** body with no `Content-Length` | **Falsified.** All 8 → `413 {"detail":"Request body too large"}`, including the chunked case (the middleware reads until `more_body` is false and counts as it goes). The ceiling is path-independent, as is the strict-JSON gate. |
| V3 | XSS via the server-side email/PDF templates (`app/templates/email/alert.html`, `email/test.html`, `report/report.html`) | grep for `|safe` / `autoescape` / `Environment` across `app/templates/` and `alerting.py`; trace the single `Markup()` call in `reports.py` | **Falsified.** All three templates render through Jinja2 `Environment(..., autoescape=select_autoescape(["html"]))` — `alerting.py:36-38`, `reports.py:48-51`. There is **no `|safe` and no `autoescape=False` anywhere in `app/templates/`**. The one `Markup()` call, `reports.py:188 timeline_svg=Markup(timeline_svg(data))`, is justified: `timeline_svg` (`reporting.py:216-257`) interpolates only floats and ints — `h.risk_score`, `data.site.flag_threshold`, integer indices — through `:f` / `:.1f` specifiers, with values clamped by `max(0.0, min(1.0, risk))` before formatting. Site names, URLs, AI explanations and evidence values all flow through the autoescaped template context. **WeasyPrint's HTML→PDF path is not an injection surface.** |
| V4 | `markdown-message.tsx` (the client Markdown renderer, reachable with LLM output) uses `dangerouslySetInnerHTML` | full read of the file | **Falsified.** It maps every element to React components (`p`, `ul`, `a`, `code`, `table`, …), imports **no `rehype-raw`**, and never touches `innerHTML`. Raw HTML from model output renders as inert text. `tests/ui-enhancements.test.tsx:57,67` assert this with hostile fixtures and pass. |
| V5 | The custom listbox menus (audit, users-card, remediation-hooks, `ui/select`) trap keyboard focus or ignore `Escape` | grep for `Escape` and window-level listeners; read `src/lib/listbox-keys.ts` | **Falsified.** All four own a window-level `Escape` listener returning focus to the trigger, and the shared model returns `dismiss` on `Tab` specifically so focus is *not* yanked back. `listbox-keys.ts`'s header documents the deliberate choice, and the file has unit-test coverage. |
| V6 | The rate limiter has a fail-open mode, or multi-worker uvicorn multiplies the budget | read `FixedWindowLimiter`; `Dockerfile.app:55`; the compose app service | **Falsified.** Storage is an in-process `dict` with no external dependency — no Redis round-trip, so no dependency failure can open the limiter. `Dockerfile.app:55` is `CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]` with no `--workers`, and the compose app service sets no `command:` override, so the shipped topology is a single process. (A future `--workers` would reintroduce the N× bypass — a fragility, not a finding.) |
| V7 | API-key rotation, or parallel sessions, resets the per-user rate-limit budget | code-trace `deps.py:97` | **Falsified.** The bucket is keyed `f"user:{user_id}"`, so rotating keys and parallel sessions share one budget. |
| V8 | `Retry-After` is wrong on 429 | measured with `RATE_LIMIT_PER_IP=2` | **Falsified.** `Retry-After: '59'` on a 60 s window, from `max(1, int(window.reset_at - now))` (`ratelimit.py:67`). No rate-limit headers on 2xx, which 4C already recorded as acceptable. |
| V9 | CSRF is possible against a cookie-authenticated state-changing endpoint | cross-origin-shaped requests (`Origin: https://evil.test` + `Referer` + form `Content-Type`) on 4 mutating routes; preflight `OPTIONS`; cookie-only requests with a forged `wardress_refresh` | **Falsified, and the architecture is sound.** Every mutating route → `401 {"detail":"Not authenticated"}` with **no** `Access-Control-Allow-Origin` and **no** `Access-Control-Allow-Credentials`. Cookie-only `POST /api/auth/refresh`, `POST /api/auth/logout`, `GET /api/sites`, `POST /api/sites`, `GET /api/health/details` → all 401. Preflight `OPTIONS /api/sites` → `405 Method Not Allowed` (`Allow: POST`), because with the default empty origin list **no CORS middleware is registered at all**. The reason is structural: the only cookie that travels is `wardress_refresh`, and it is `HttpOnly; Max-Age=604800; Path=/api/auth; SameSite=strict` (measured `set-cookie`), so `SameSite=strict` prevents it from being sent on any cross-site request; and the access token is in JS module memory (`api.ts:9`), never a cookie, so no cross-origin page can attach it. There is no CSRF token, and none is needed for this credential model. (`Secure` is absent by default because `COOKIE_SECURE=false`, which is documented in `README.md`; `SameSite=strict` is what covers the plain-HTTP default.) |
| V10 | The deployed container runs stale code (AUDIT-4B-8's precondition) | `docker cp` + `git hash-object` on 10 audited files | **Falsified.** 10/10 MATCH, 0 mismatches. |
| V11 | Orphan model columns, never-imported components, or dead `src/lib/*` exports are accumulating | repo-wide sweeps of all 137 mapped columns, all 24 component files, and 11 `src/lib` modules | **Falsified.** 0 model columns unread outside `models.py`; 0 components never imported; 0 dead exports outside `api.ts`. The dead surface is concentrated in `api.ts` (AUDIT-SA4-10) plus two schema fields. |
| V12 | There is an unbounded or unbounded-parameter endpoint beyond the site list | 11 query-string shapes against all 4 paginated endpoints; bare-array endpoints probed with `limit`/`offset` | **Partially falsified.** Every endpoint that *declares* pagination is correctly bounded and rejects negative offset, `limit=0`, `limit>200`, non-integers and floats (see AUDIT-SA4-8's table). The bare-array endpoints all ignore `limit`/`offset`, but all are naturally small; only the site list is materially large, and that is filed as AUDIT-SA4-8. |

---

## 1. Route Inventory / Authn-Authz Matrix

**85 `APIRoute` operations across 15 mounted routers, plus 4 FastAPI doc routes and 1 static SPA mount.** Enumerated from `app.routes` by walking `_IncludedRouter.original_router` (this FastAPI version's nested-router representation), then cross-checked against the in-process OpenAPI document (65 paths, 85 operations, 81 declaring `security`).

### Intentionally public — 4 operations (and only these 4 declare no `security` in the schema)

| Method | Path | Authn | Why public | Verified behaviour |
|---|---|---|---|---|
| POST | `/api/auth/login` | none (body credentials) | the login itself | 401 on bad creds; 429 after 5 failures |
| POST | `/api/auth/refresh` | `wardress_refresh` cookie (`SameSite=strict`, path `/api/auth`) | rotating refresh token | 401 on missing/forged/replayed/expired |
| GET | `/api/health/live` | none | compose healthcheck target (`docker-compose.yml:83`) | `200 {"status":"ok"}` even with the DB down |
| GET | `/api/health` | none | readiness probe | see AUDIT-SA4-9 / AUDIT-4C-5 |

### Unintentionally public — 4 routes

All four are FastAPI's doc surface: none is set in the ctor (`main.py:52-57`) and none is metered (the rate-limit middleware matches only paths starting `/api/`).

| Method | Path | Bytes served (live) | Note |
|---|---|---|---|
| GET | `/openapi.json` | **92,500** | no `Cache-Control`; 78 component schemas, 85 operations |
| GET | `/docs` | 1,007 | Swagger UI |
| GET | `/redoc` | 889 | ReDoc |
| GET | `/docs/oauth2-redirect` | 3,012 | **not enumerated by 4C** — an extra public HTML surface with its own JS |

**Total unintentionally-public route count: 4.** All are doc routes; **zero `/api/` data routes are unintentionally public**. `/favicon.ico` returns `200` with the SPA shell via the `SPAStaticFiles` fallback, which is the intended static mount, not a leak.

### Authenticated, any role (viewer floor) — 26 operations

All take `CurrentUser` (`deps.py:126`) → `get_auth_context` → the per-user rate-limit charge:

`GET /api/alerts`, `GET /api/alerts/{alert_id}`, `GET /api/sites`, `GET /api/sites/{site_id}`, `GET /api/sites/{site_id}/scans`, `GET /api/sites/{site_id}/scans/{scan_id}`, `GET /api/sites/{site_id}/suppression-rules`, `GET /api/sites/{site_id}/icon`, `GET /api/auth/me`, `GET /api/health/details`, `GET /api/reports/{scan_id}/markdown`, `GET /api/reports/{scan_id}/pdf`, `GET /api/artifacts/baselines/{baseline_id}/{html,screenshot}`, `GET /api/artifacts/scans/{scan_id}/{html,screenshot}`, 10 `GET /api/settings/*` read endpoints (incl. `ai/catalog/providers`), `GET /api/api-keys`, and 3 `GET /api/agent/*` (out of scope).

### Role floors — 39 mutating operations, exhaustively fuzzed

Probe: every non-GET route × {no credential, viewer, analyst, admin} = **156 requests**, all status codes recorded:

| Floor | Count | Operations |
|---|---|---|
| analyst (admin + analyst) | 12 | `POST /api/sites`, `POST /api/sites/bulk-import`, `PATCH`/`DELETE /api/sites/{id}`, `POST /api/sites/{id}/rebaseline`, `POST /api/sites/{id}/scan-now`, `POST`/`DELETE /api/sites/{id}/suppression-rules[/{rule_id}]`, `POST /api/sites/{id}/scans/{scan_id}/explain`, `POST /api/alerts/{alert_id}/ack`, `POST /api/api-keys` (create) |
| admin only | 24 | all `/api/users*`; all `/api/notification-channels*`; all `/api/settings/*` writes; `POST /api/remediation/executions/{id}/{confirm,dismiss}`; `POST /api/agent/actions/{id}/{confirm,cancel}`; `GET /api/audit-log`; the four `/api/sites/{id}/remediation-hooks*` operations |
| session-only (any role, API keys refused with 403) | 3 | `GET /api/api-keys`, `DELETE /api/api-keys/{key_id}`, `POST /api/auth/logout` — all via `SessionAuthContext` (`deps.py:135-149`) |

**Result: zero RBAC holes.** Every mutating route returned `401` with no credential and `403` for viewer, without exception. Selected rows of the live matrix:

```
METHOD PATH                                                   none   view   anal   admin
POST   /api/sites                                              401    403    422    422
POST   /api/sites/bulk-import                                  401    403    422    422
PATCH  /api/sites/{site_id}                                    401    403    404    404
DELETE /api/sites/{site_id}                                    401    403    404    404
POST   /api/sites/{site_id}/scan-now                           401    403    404    404
POST   /api/sites/{site_id}/scans/{scan_id}/explain            401    403    404    404
POST   /api/sites/{site_id}/remediation-hooks                   401    403    403    422   <- admin-only
POST   /api/alerts/{alert_id}/ack                              401    403    404    404
POST   /api/remediation/executions/{execution_id}/confirm      401    403    404    404
POST   /api/notification-channels                               401    403    403    422
POST   /api/settings/ai/providers/{provider_id}/validate        401    403    403    422
POST   /api/users                                              401    403    403    422
PATCH  /api/users/{user_id}                                    401    403    403    404
DELETE /api/users/{user_id}                                    401    403    403    404
POST   /api/api-keys                                           401    403    422    422   <- analyst floor
DELETE /api/api-keys/{key_id}                                  401    404    404    404   <- own keys only
POST   /api/auth/logout                                        401    204    204    204
```

Notable **tightening** worth recording as a positive: per-site **remediation hooks are admin-only** even though per-site settings are analyst-gated, because those hooks fire outbound POSTs to attacker-influenceable receivers. And **role demotion is immediate** (measured, AUDIT-SA4-13) because `require_roles` re-reads `user.role` from the database rather than trusting the token's claim.

**Intent mismatches found:** none in the decorator/dependency layer — the enforcement matches the declared floors everywhere. The two contract mismatches are at the *documentation* layer: `DELETE /api/users/{id}`'s "never-used accounts" precondition (AUDIT-4C-7) and `health.py`'s compose-healthcheck citation (AUDIT-4C-5).

**Tenant / account data scoping.** There is no tenant concept in this product (single deployment, many users), so no route's query needs an account predicate beyond the user-owned ones. The per-user predicates that do exist were traced and are correct: `apikeys.py:33` and `:67` both filter `ApiKey.user_id == ctx.user.id` (a viewer receives `404`, not another user's key — measured); `sites.py:376`, `:404-405`, `:468`, `:513-515` all filter by the path's `site_id`; `reports.py` resolves the scan and then the site independently, which is correct for a single-tenant model. **No cross-account leakage found.**

---

## 2. Dead Code & Orphan Routines

Every row is backed by the grep counts in the Evidence column (repo-wide, excluding `node_modules`, `dist`, `Prompts`, `landing`, `walkthrough`, `.venv`, `__pycache__`).

| file:line | symbol | kind | proof (grep hits) |
|---|---|---|---|
| `backend/app/security.py:47` | `role` JWT claim | dead payload field | `payload["role"]` → 1 hit, a test assertion (`tests/test_security.py:42`); `payload.get("role")` → 0 hits. No production reader; `deps.require_roles` reads `user.role` from the DB. |
| `backend/app/deps.py:128` | `AnyRoleUser` | dead alias | 1 hit repo-wide (its own definition). |
| `backend/app/routers/users.py:99-100` | "Role rides in the access token; cut sessions…" | stale comment | The token's `role` claim is never read (row 1), so the refresh revocation the comment justifies is not the enforcement point — demotion is already immediate. |
| `backend/app/routers/health.py:226` vs `backend/app/routers/sites.py:74` | degraded predicate | duplicated logic | Both `get("degraded")` predicate lines verbatim; neither imports the other; `_has_degraded_layer` → 2 hits (definition + its own single use). |
| `backend/app/schemas.py:86` vs `backend/app/services.py:57` | `le=7 * 24 * 60` vs `MUTE_CAP_MINUTES` | duplicated constant | Two independent definitions of the same 7-day mute cap, no shared source. |
| `frontend/src/lib/api.ts:654,656,658,663,664,666,671,672` | `getGeminiSettings`, `putGeminiSettings`, `addGeminiKey`, `removeGeminiKey`, `testGemini`, `getOllamaSettings`, `putOllamaSettings`, `testOllama` | dead client fns → dead routes | 1 hit each (the definition). The 8 backend routes are live and admin-writable. |
| `frontend/src/lib/api.ts:691` | `listCatalogModels` | dead client fn → dead route | 1 hit. `GET /api/settings/ai/catalog/models` unreachable from the UI. |
| `frontend/src/lib/api.ts:706` | `updateAiProvider` | dead client fn → **functional gap** | 1 hit. No UI path to edit an existing AI provider. |
| `frontend/src/lib/api.ts:721` | `validateAiProvider` | dead client fn → SSRF-probing route with no caller | 1 hit. `POST /api/settings/ai/providers/{id}/validate` reachable only by hand. |
| `frontend/src/lib/api.ts:1006` | `deleteUser` | dead client fn → dead route | 1 hit. `DELETE /api/users/{id}` has no UI caller (lowers AUDIT-4C-7's reachability). |
| `frontend/src/components/ui/table.tsx:97-118` | `TableCaption` | unused primitive | `TableCaption` → `ui/table.tsx` only; `scope=` / `<caption` → 0 hits in `src/`. |
| `backend/app/schemas.py` `BaselineOut.captured_at` | `captured_at` | orphan response field | 0 references in `frontend/src`; 0 in `frontend/tests`. |
| `backend/app/schemas.py` `BaselineOut.is_current` | `is_current` | orphan response field | 0 references in `frontend/src`; 0 in `frontend/tests`. |
| `backend/app/schemas.py` `SiteDetailOut.consecutive_degraded_scans` | `consecutive_degraded_scans` | orphan response field (AUDIT-4F-2's core) | 9 references in `frontend/tests`, **0** in `frontend/src`. |
| — | model columns | **none found** | All 137 mapped columns swept; **0** unread outside `models.py` (the single regex hit, `refresh_tokens`, is a `relationship()`, not a column). |
| — | frontend components | **none found** | All 24 component files swept; **0** never imported. |
| — | `src/lib/*` non-`api.ts` modules | **none found** | 11 modules swept (auth, artifacts, icons, keyboard, numeric, reduced-motion, site-avatar, icon-state, utils, task-assignment, bbox); **0** dead exports. |
| — | dead CSS classes | **not assessed** | Out of the achievable budget for this subagent; Tailwind's JIT generates CSS from used classes, so a class-name grep would be unreliable. **Explicitly not claimed.** |

---

## 3. Opportunities for Optimization

| proposal | target file(s) | measured / projected impact | risk |
|---|---|---|---|
| **Route-level `React.lazy` for the 9 non-default routes** | `frontend/src/App.tsx:6-15` (+ a `<Suspense>` fallback) | **Measured** in a controlled out-of-repo rebuild: eager chunk 1,077.4 kB / 404.4 kB gzip → **268.5 kB / 83.4 kB gzip** (−75.1% raw, −79.4% gzip) on the login page. | **Low-medium.** Every route becomes a Suspense boundary, so the fallback must be designed rather than `null`. Consider keeping `SitesPage` eager since it is the post-login landing route. |
| **Move provider logos behind a dynamic import map, or raise `assetsInlineLimit` for them** | `frontend/src/lib/provider-logos.ts` (161 static imports), `frontend/vite.config.ts` | **Measured**: 107 base64 data URIs = **205.5 kB** of the eager chunk (19.1%). Independent of, and additive to, route splitting — the variant build moved all 107 into the `settings` chunk. | **Low.** `tests/ai-provider-logo.test.tsx` (18 tests) and `tests/svg-path-integrity.test.ts` (2 tests) both cover this file and must stay green. |
| **Isolate `react-markdown` + `remark-gfm` behind a lazy import in `MarkdownMessage`** | `frontend/src/components/markdown-message.tsx:1-2` | **Measured**: 146.4 kB attributed in the eager chunk (13.6%); the variant isolates it as a 155.95 kB / 46.36 kB gzip chunk. Only 2 of 10 routes need it. | **Low.** `tests/ui-enhancements.test.tsx` (8 tests) asserts the rendered output. |
| **Paginate `GET /api/sites`** (offset/limit + `total`, copying the `/api/audit-log` contract) | `backend/app/routers/sites.py:139-206`, `frontend/src/pages/sites.tsx`, `frontend/src/lib/api.ts` (`listSites`) | **Measured**: 600 sites → a single 364,581-byte array, with `limit`/`offset` silently ignored. At 600 rows the landing route parses 356 KB on every visit and then issues up to 600 `/icon` requests at **2 budget units each** against a 240/min budget. | **Low-medium.** Bulk import admits 500 rows per call, so 600 is one import's worth — pagination is the difference between "installs are small" and "installs are large". |
| **Dedupe `useSiteIcon` / `useArtifact` into React Query** | `frontend/src/lib/use-site-icon.ts`, `use-artifact.ts`, and their 5 call sites (`site-favicon`, `site-avatar`, `visual-diff-slider`, `dom-diff-tree`, `suppression-panel`) | 4F's own note, now quantified: **one HTTP request per component mount**, no dedupe, no TTL, blob URL revoked per unmount. Multiplier: `GET /api/sites/{id}/icon` costs **2** of the per-user budget (AUDIT-4C-6), so an N-row list costs **2N**. | **Low.** Needs a refcounted blob registry to avoid revoking a URL another component is still displaying. |
| **Consolidate the two site-detail scan queries into one** | `frontend/src/pages/site-detail.tsx:333-356`, `:58` | **Measured**: 3 requests per mount, two differing only in `limit` (20 and 200), with independent 2 s / 5 s poll timers and separate caches. `TIMELINE_WINDOW = 200` also over-fetches for a chart. One `listScans(0, 200)` with a per-consumer `select` removes one request and one timer. The other views already issue only 1–3 requests, so this is a local change. | **Low.** Prefix invalidation (`["sites", id, "scans"]`) already covers both keys; no invalidation change needed. |
| **Add a bundle-size budget to CI** | `frontend/vite.config.ts`, `.github/workflows/ci.yml` | Prevents re-monolithisation: the only current signal is Vite's generic ">500 kB chunk" warning. A size assertion on `dist/assets/index-*.js` would have caught this. | **Very low.** |
| **Add `aria-live` regions + a root error boundary + a `paged()` shape validator** | `frontend/src/App.tsx`, `src/lib/api.ts`, the 4 polling pages | Not a size win — closes 6 blank-page shapes (AUDIT-4F-3) across 4 routes, takes the live-region count from 0 to 1 (AUDIT-SA4-6), and turns the two "no measurement" states into announceable ones. | **Low.** Three independent findings; the boundary fixes the *symptom* of 4F-3, the validator fixes the *cause*. |
| **Audit-log `actor` LIKE escaping** | `backend/app/routers/audit.py:38-39` | **Measured**: `%` and `_` act as wildcards; `actor=%` matches every row. Correctness only. | **Very low.** |
| **Region-specific: run the Tier-C RTL sites after the bidi fix, not before** | `frontend/src/pages/site-detail.tsx`, `dom-diff-tree.tsx`, `finding-card.tsx` | The bidi gap (AUDIT-4F-6) is latent *today*, but Tier C (`aljazeera.net`, `bbc.com/arabic`, `haaretz.co.il`) exists precisely to exercise it. Fixing first is cheaper than re-auditing rendered screenshots afterwards. | **Very low.** |
| **Make the 12 dead client functions either live or absent** (AUDIT-SA4-10) | `frontend/src/lib/api.ts`, `backend/app/routers/settings.py`, `users.py` | Closes 11 admin routes that are live, write-capable, publicly advertised, and (for 6 of them) marked `DEPRECATED`, with zero callers. Also closes a functional gap: there is no UI path to edit an existing AI provider. | **Very low** — deletion is mechanical, but must be paired with a decision on whether the deprecated backend routes should also be retired. |

---

## 4. Summary

### Counts by classification

| Classification | Count | IDs |
|---|---|---|
| **CONFIRMED** | 8 | AUDIT-4C-3, AUDIT-4C-6, AUDIT-4F-2, AUDIT-4F-5 (≡ AUDIT-2B-5), AUDIT-4F-6, AUDIT-4F-7, AUDIT-4F-8, AUDIT-4F-9 |
| **DEEPENED** | 8 | AUDIT-4C-1, AUDIT-4C-2, AUDIT-4C-4, AUDIT-4C-5, AUDIT-4C-7, AUDIT-4F-1, AUDIT-4F-3, AUDIT-4F-4 |
| **NEW** | 13 | AUDIT-SA4-1 … AUDIT-SA4-13 |
| **INVALIDATED** | 1 partial | AUDIT-4C-2's "`wk_` key prefix" example — **not reproducible**: 0 hits over the 99,585-byte schema; the prefix lives in `app/apikeys.py`, not in the published schema. The finding itself stands on 8 stronger evidence items. |
| Verified-clean hypotheses falsified | 12 | V1–V12 |

**Total finding blocks: 29** (8 CONFIRMED + 8 DEEPENED + 13 NEW), plus 1 partial invalidation noted inside AUDIT-4C-2.

### Severity distribution (one severity per finding, §6.4)

| Severity | Count | Findings |
|---|---|---|
| **Critical** | **0** | — |
| **High** | **0** | — |
| **Medium** | **10** | AUDIT-4C-1, AUDIT-4C-2, AUDIT-4F-2, AUDIT-4F-3, AUDIT-SA4-1, AUDIT-SA4-2, AUDIT-SA4-3, AUDIT-SA4-5, AUDIT-SA4-8, AUDIT-SA4-9 |
| **Low** | **19** | AUDIT-4C-3, AUDIT-4C-4, AUDIT-4C-5, AUDIT-4C-6, AUDIT-4C-7, AUDIT-4F-1, AUDIT-4F-4, AUDIT-4F-5, AUDIT-4F-6, AUDIT-4F-7, AUDIT-4F-8, AUDIT-4F-9, AUDIT-SA4-4, AUDIT-SA4-6, AUDIT-SA4-7, AUDIT-SA4-10, AUDIT-SA4-11, AUDIT-SA4-12, AUDIT-SA4-13 |

**Zero Critical and zero High is a deliberate, defended position, not a soft one.** The RBAC matrix (156 fuzzed requests across 39 mutating routes × 4 credential states) found **zero** authorization holes. CSRF is structurally impossible given the credential model (11 cross-origin/cookie-only probes, all 401, preflight 405). XSS is ruled out in all three server-side templates and in the client Markdown renderer. Content-Type validation and the body-size ceiling are both genuinely enforced on every path. Pagination bounds hold everywhere they are declared. The rate limiter has no fail-open mode and is not per-worker-divisible in the shipped topology. What remains is a set of **contract-honesty**, **availability-under-configuration**, and **presentation** defects — all real, all measured, none an authentication or data-integrity break.

### New test files added

**None.** SA4 added **zero** files to the repository and made **zero** git changes of any kind.

Rule 1 permits committed hermetic tests, but I deliberately did not exercise that allowance: every probe was either (a) an assertion-free measurement (RBAC matrix, request census, bundle attribution, LIKE sweep, delay sweep, cascade counts), or (b) a defect repro whose entire value lies in its recorded output. Committing a defect repro would require either `xfail` or pinning the bug as correct behaviour, and in both cases the committed artifact would be worth less than the measurement scripts, which are preserved under the scratch directory below.

**Scratch artifacts preserved** (all outside the repo, per Rule 10):
```
C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-a\api-frontend\
  route_inventory.py          full route/dependency enumeration (85 operations)
  probes\conftest.py          mirror of backend/tests/conftest.py, outside the repo
  probes\pytest.ini
  probes\probe1_rbac_matrix.py     156-request RBAC fuzz matrix
  probes\probe2_request_shape.py   Content-Type bypass, body ceiling, pagination bounds, health oracle
  probes\probe3_authn_ratelimit.py session invalidation, lockout DoS, XFF/IPv6 bypass, double-charge, Retry-After
  probes\probe4_openapi.py         99,585-byte schema introspection + pattern sweep
  probes\probe5_cors_leak.py       cross-origin/CSRF, cookie attributes, error-body leakage
  probes\probe6_surface_e2e.py     4C-1/4C-2/4C-5/4C-7 HTTP probes
  probes\probe7_cascade.py         4C-1 bulk-import contrast, 4C-4/4C-7 cascade footprints, in-flight guards
  probes\probe8_unbounded.py       unbounded list growth, audit-log LIKE metacharacters, channel redaction
  attribute_chunk.py          sourcemap-VLQ byte attribution of a built chunk
  group_chunk.py              the same, grouped by asset/package/page
  part1.md / part2.md / part3.md  the sections of this report
```

**Three scratch vitest files were created under `frontend/tests/` and DELETED before this report was finalised**: `_scratch-sa4-shape.test.tsx` (19-shape malformed-payload sweep), `_scratch-sa4-flake.test.tsx` (13-point delay sweep + 12 repeatability passes), `_scratch-sa4-fetch.test.tsx` (per-view request census). All three intentionally attach `process` handlers for errors that escape React, so leaving them in place would have made `vitest run` exit 1 despite all tests passing — the exact trap Phase 4F hit. Deletion is verified: `Get-ChildItem tests -Filter "_scratch*"` returns empty and the full suite exits 0.

### Exact commands run, with results

**Backend — probes (all with `$env:WARDRESS_TEST_DATABASE_URL = "postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_api_test"`, from `backend\`, via `.\.venv\Scripts\python.exe -m pytest`)**
```
probe1_rbac_matrix.py        -> 1 passed   (156-request matrix printed)
probe2_request_shape.py      -> 1 failed, 2 passed  -> after fixing an ImportError in MY probe
                                 (`from app.services import services`, a bad import of mine):
                                 re-run -> 4 passed
probe3_authn_ratelimit.py    -> 8 passed
probe4_openapi.py            -> ran as a script (not pytest); 99,585-byte schema dumped
probe5_cors_leak.py          -> 3 passed
probe6_surface_e2e.py        -> 3 passed, 1 error  -> error was in MY fixture (wrong FK column
                                 name / CSV header); the 4C-1 HTTP result was captured before it
probe7_cascade.py            -> 3 passed (after 3 fixture corrections of mine)
probe8_unbounded.py          -> 3 passed
```

**Backend — regression suite (Rule 5)**
```
$env:WARDRESS_TEST_DATABASE_URL = "postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_api_test"
.\.venv\Scripts\python.exe -m pytest tests/test_phase4c_api_surface_repros.py tests/test_phase4_api.py \
  tests/test_auth.py tests/test_phase5_rbac.py tests/test_phase5_users_apikeys.py \
  tests/test_phase5_ratelimit_ssrf.py tests/test_phase5_health.py tests/test_sites_router_integrity.py \
  tests/test_phase17_auth_audit.py tests/test_main.py tests/test_security.py tests/test_phase5_audit.py -q
  -> 168 passed, 1 warning in 167.30s (0:02:47)
```
The single warning is `apprise/utils/pgp.py`'s `imghdr` DeprecationWarning — pre-existing, unrelated to this work.

**Frontend**
```
cd frontend
pnpm build                          -> built in 6.22s; index-BH4_Nm0m.js 1,103.50 kB / gzip 417.54 kB
                                       (+ Vite's ">500 kB chunk" warning — the only signal that exists today)
pnpm exec vite build --sourcemap    -> built in 2.42s; 4 .map files written to dist/assets
pnpm exec vitest run                -> 22 files / 144 tests / 0 failed, exit 0 (17.84 s)
pnpm exec vitest run                -> 22 files / 144 tests / 0 failed, exit 0 (53.16 s, cold transform)
pnpm exec vitest run                -> 22 files / 144 tests / 0 failed, exit 0  (3rd pass, after scratch deletion)
pnpm exec tsc -b                    -> exit 0, no output
pnpm exec oxlint src                -> exit 0; 12 warnings, 0 errors on 54 files
```
**Phase-4F's two committed guards pass at HEAD as part of that 144-test run**: `tests/phase4f-capture-surface-repros.test.tsx` (11 tests, 2,760 ms) — including `AUDIT-4F-9` whose stderr still shows React's own *"An error occurred in the `<SiteDetailPage>` component. Consider adding an error boundary…"*, which is the direct evidence for AUDIT-4F-3 — and `tests/capture-health.test.tsx` (4 tests, 1,472 ms).

**Scratch frontend probes (each run against the live `frontend/tests/` include glob, then deleted)**
```
pnpm exec vitest run tests/_scratch-sa4-shape.test.tsx  -> 19 passed (5.25 s)
pnpm exec vitest run tests/_scratch-sa4-flake.test.tsx  -> 25 passed (27.25 s)
pnpm exec vitest run tests/_scratch-sa4-fetch.test.tsx  -> 5 passed / 3 failed (9.58 s)
      the 3 failures were MY stub returning the wrong shape for SitesPage / RemediationPage /
      SettingsPage (they need an auth context my harness does not provide); the census rows that
      matter — health, alerts, audit, site-detail, scan-detail — all rendered and were measured.
```

**Live-stack verification (read-only)**
```
$base="http://localhost:8321"
GET /api/health /api/health/live /api/health/details /openapi.json /docs /redoc
GET /docs/oauth2-redirect /favicon.ico /api/sites
  -> 200 200 401 200(92500) 200(1007) 200(889) 200(3012) 200(506) 401
container parity: docker cp + git hash-object on 10 files -> 10/10 MATCH, 0 mismatches
CORS wildcard probe: a separate process with CORS_ALLOWED_ORIGINS="*" -> any origin reflected with ACAC: true
```

**No `pnpm audit` / `uv`-based supply-chain sweep was run** — that is Phase 4E's territory and AUDIT-4E-10/11 remain as 4E left them. AUDIT-4E-11's `ruff format --check .` 24-file failure was deliberately **not** re-run and not touched (Rule 1).

### Live stack left clean

- **No live user, site, API key, notification channel, agent conversation, remediation hook or suppression rule was created.** Every mutable operation ran against `wardress_sa_api_test` on the disposable `wardress-test-pg` container, which is a scratch database I created for this session.
- **No container was stopped, restarted, or rebuilt.** No install/uninstall script was run.
- The only writes to the live stack's *filesystem* were `docker cp` reads (into a temp directory) and the frontend `dist/` rebuild — `dist/` is gitignored and is not served by the container.
- `git status --porcelain` at the end shows only the three untracked files belonging to **other concurrent subagents** (`test_phase_sa3_orchestration_deep.py`, `test_phase_sa5_ai_infra_repros.py`, `test_session_a2_detection_findings.py`). SA4's footprint on the repository is **zero files, zero edits, zero git state changes**.
- The probe audit rows that exist in `wardress_sa_api_test` are in my own scratch database, not the live one, so there is nothing to clean there either.
