# PROGRESS.md — Wardress living memory

> Appended at the end of every phase per `WARDRESS_MASTER_PROMPT.md` §14.
> Newest entries at the bottom. Never rewrite history — append corrections.

---

## Phase 0 — Foundations & offline readiness (2026-07-16)

### Architecture decisions (seeded from the master prompt + Phase 0 findings)

**PDF engine: WeasyPrint, not Playwright.**
Playwright *could* print-to-PDF, but: (a) it would couple report generation
to a heavyweight browser process that competes with scan jobs for the same
worker resources; (b) WeasyPrint implements CSS Paged Media properly
(running headers/footers, numbered pages, page-break control around tables
and images) which browser print-to-PDF handles poorly; (c) report rendering
must work even if the browser pool is saturated or wedged. Cost: Pango/
Cairo/GDK-PixBuf system libs in the worker image — already installed in
`backend/Dockerfile.worker`.

**Frontend serving: built static bundle served by the FastAPI `app`
container. No nginx.**
Rationale: one fewer container on a self-hosted single-user Windows box,
no reverse-proxy config to maintain, FastAPI's `StaticFiles(html=True)`
serves the SPA fine at this scale, and same-origin serving eliminates the
CORS surface entirely (dev mode uses Vite's proxy for `/api` instead).
Revisit only if static serving measurably competes with API latency —
noted as a non-goal for a monitoring dashboard.

**Telegram bot: dedicated small container (`telegram-bot` service), not a
thread inside `worker`.**
Rationale: long-polling `run_polling()` wants to own its event loop and
its lifecycle (restart on token change) independently of scan workers;
a wedged bot must never affect scanning, and Celery worker prefork
processes are a hostile place for a persistent asyncio loop. It reuses
the worker image (no extra build), and is behind a compose profile
(`--profile telegram`) so it costs nothing unless enabled. Phase 0 ships
a stub (`worker/telegram_stub.py`); the real bot lands in Phase 4.

**Ollama: compose profile (`--profile ollama`), not an env-flag branch in
app code.** Cleanest way to make a whole container optional; the
`ENABLE_OLLAMA` env var remains for the app to know whether to offer the
option in Settings UI (Phase 4).

**CPU-only torch enforcement:** `sentence-transformers` transitively pulls
torch, which by default resolves CUDA variants (~70 nvidia-* packages
appeared in the first lockfile). Fixed by declaring `torch>=2.5` as a
direct dependency and pinning it to the `https://download.pytorch.org/whl/cpu`
index via `[tool.uv.sources]` in `backend/pyproject.toml`. Verified: zero
`nvidia*` entries in `uv.lock`, installed wheel is `2.13.0+cpu`.
(Master prompt rule 3: no GPU dependencies, ever.)

### Version verification log (rule 2 — all checked against live registries 2026-07-16)

Backend (PyPI): fastapi 0.139.0 · uvicorn 0.51.0 · sqlalchemy 2.0.51 ·
alembic 1.18.5 · asyncpg 0.31.0 · celery 5.6.3 · redis 8.0.1 ·
**playwright 1.61.0 (pin from master prompt confirmed current)** ·
lxml 6.1.1 · scikit-image 0.26.0 · imagehash 4.3.2 ·
sentence-transformers 5.6.0 · scikit-learn 1.9.0 · httpx 0.28.1 ·
google-genai 2.12.0 · aiolimiter 1.2.1 · apprise 1.12.0 ·
python-telegram-bot 22.8 (satisfies the v22.x pin) · jinja2 3.1.6 ·
premailer 3.10.0 · aiosmtplib 5.1.2 · weasyprint 69.0 ·
argon2-cffi 25.1.0 · pyjwt 2.13.0 · cryptography 49.0.0 ·
pydantic-settings 2.14.2 · pytest 9.1.1 · pytest-asyncio 1.4.0 ·
ruff 0.15.21 · pip-audit 2.10.1 · torch 2.13.0+cpu

Frontend (npm): react/react-dom 19.2.7 · vite 8.1.4 ·
@vitejs/plugin-react 6.0.3 · tailwindcss + @tailwindcss/vite 4.3.2 ·
recharts 3.9.2 · @tanstack/react-query 5.101.2 · react-router 8.2.0 ·
lucide-react 1.24.0 · vitest 4.1.10 · typescript 7.0.2 (bundled by
create-vite template)

Images: `postgres:16` (per master prompt §1 pin; 18 exists but the pin is
source of truth) · `redis:8-alpine` · `mcr.microsoft.com/playwright/python:v1.61.0-noble`
(tag existence verified against MCR) · `ghcr.io/astral-sh/uv:0.9.2`
(matches the host uv version for consistency).

Toolchain: uv 0.9.2 · pnpm 11.13.1 (upgraded from 10.6.5 during Phase 0 —
see incident log) · node 22.14.0 · Docker 28.3.2.

### What was built

- Repo skeleton exactly per §12; git initialized on `main`.
- `backend/`: uv project, locked (`uv.lock`, 167 packages), hello-world
  FastAPI app with `/api/health`, Celery app with `wardress.ping`
  self-test task (task_acks_late=True from day one — crashed workers must
  never drop scans), Alembic initialized with the **async template**, and
  `env.py` patched to read `DATABASE_URL` from the environment (no
  credentials in committed files; `alembic.ini` URL intentionally blank).
- `frontend/`: Vite + React 19 + TS + Tailwind v4 via `@tailwindcss/vite`.
  Design tokens from `DESIGN-resend.md` translated into a Tailwind v4
  `@theme` block in `src/index.css` (colors/surfaces/hairlines/glows/radii).
  Fonts intentionally deferred to Phase 1 (shell layout work). Placeholder
  App shell renders on the true-black canvas. Vitest + Testing Library
  wired; `packageManager` pinned.
- `docker-compose.yml`: `db` (postgres:16), `redis` (8-alpine), `app`
  (FastAPI + static frontend, multi-stage build), `worker` (Playwright
  base image + WeasyPrint system libs), `beat`, `telegram-bot` (profile),
  `ollama` (profile). Healthchecks on db/redis/app; `depends_on` gated on
  health. Required secrets use `${VAR:?}` so compose fails loudly if the
  `.env` is missing rather than starting with empty credentials.
- Dockerfiles follow the official Astral uv pattern (verified against the
  live docs, cached in `docs-cache/uv-docker.html`): uv binary copied from
  the pinned `ghcr.io/astral-sh/uv:0.9.2` image, dependency layer
  (`uv sync --frozen --no-install-project --no-dev`) before source copy,
  `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, cache mounts.
- `.env.example` with CHANGE_ME markers (install.ps1 will generate real
  secrets in Phase 6); dev `.env` generated locally with random secrets,
  gitignored.
- `reference/changedetection.io` shallow-cloned (22 MB, gitignored).
- `docs-cache/`: 24 documentation snapshots + `fetch-docs.sh` (see its
  README for fallbacks used).
- CI (`.github/workflows/ci.yml`): backend job (ruff check + format,
  pip-audit, pytest), frontend job (pnpm audit, oxlint, tsc, vitest,
  build), compose-config validation job.

### Verified working (not just "should work")

- `uv run pytest` — 2/2 pass. `ruff check` + `format --check` — clean.
- `pnpm build`, `vitest run` (1/1), `oxlint`, `tsc -b` — all clean.
- `pip-audit`: no known vulnerabilities (torch+cpu skipped — not on PyPI,
  expected). `pnpm audit`: no known vulnerabilities.
- `docker compose up -d`: all five core services up, db/redis/app healthy.
- `GET http://localhost:8321/api/health` → `{"status":"ok"}`.
- `GET http://localhost:8321/` → built SPA served by the app container.
- Celery round-trip through Redis: `ping.delay().get()` → `"pong"`.
- Playwright Chromium launch + render **inside the worker container** — OK.
- `telegram-bot` profile service starts and idles politely without a token.

### Incidents & resolutions

- **npm retired the classic audit endpoint** (`410 Gone`); pnpm 10.6.5
  couldn't audit. Upgraded standalone pnpm to 11.13.1 (manual binary
  install — corepack couldn't write to Program Files without admin) and
  pinned `packageManager: pnpm@11.13.1` + CI to match.
  Note: during the fix, a wrong GitHub asset URL briefly overwrote the local
  `pnpm.exe` with a 404 page; restored immediately from the correct
  `pnpm-win32-x64.zip`. No repo impact.
- **readthedocs rate-limiting (HTTP 429)** blocked celery + python-telegram-bot
  doc fetches; cached their canonical GitHub sources instead (`.rst`/wiki
  `.md`). FastAPI's `llms.txt` 404'd; cached the docs homepage.
- `@testing-library/jsdom` does not exist (hallucination guard worked —
  install failed loudly); correct packages are `jsdom` + `@testing-library/react`
  + `@testing-library/dom`.
- WebFetch/WebSearch tooling intermittently unavailable in this session;
  all doc fetching done via curl into `docs-cache/` (which §2 wanted anyway).

### Deliberate deferrals (not bugs)

- Fraunces/Instrument Sans/Inter/Geist Mono font wiring → Phase 1 (with the
  shell layout + logo, per roadmap).
- Real logo mark → Phase 1; a placeholder shield favicon exists so the SPA
  doesn't 404 its icon reference.
- `scripts/install.ps1` / `update.ps1` → Phase 6 per roadmap (dir exists).
- Tagline options → Phase 1 (§3).
- No DB models/migrations yet — Alembic is initialized but has zero
  revisions; first revision lands with the Phase 1 schema.
- `pnpm audit` in CI uses `--audit-level high`: monitoring-only advisories
  below High won't block; revisit in the Phase 5 hardening pass.

---

## Phase 0 — Sign-off (2026-07-16, fresh session)

### Decision log

**Negative/malformed-input QA is deferred to manual verification by the
user, for every phase going forward.** Probing the running system with
unusual request paths, malformed/oversized headers, and malformed request
bodies will be done manually by the user in a plain terminal, **outside
Claude Code** — Claude Code and its QA subagents must not attempt this
category of live testing themselves. It is now an explicit manual step in
the phase sign-off checklist (master prompt §13, updated this session).
Claude Code still writes normal unit/integration tests for malformed-input
handling inside application code (parsers, validators, detection layers) —
the carve-out covers only live traffic against the running stack.

### Sign-off verification (re-verified directly in this session, not assumed)

- Repo structure matches §12 (scripts/ and assets/brand/ exist as
  placeholders per the deliberate-deferral log; reference/changedetection.io
  and docs-cache/ populated).
- `uv run pytest` — 2/2 pass. `pnpm vitest run` — 1/1 pass.
- Docker Compose stack: db, redis, app all healthy; worker + beat up;
  `GET /api/health` → `{"status":"ok"}`; `GET /` serves the built SPA
  (200, text/html). Celery round-trip inside the worker container:
  `ping.delay().get()` → `"pong"`. `telegram-bot` (profile service) was
  found exited 137 (killed when its profile wasn't included in a previous
  `compose up`); restarted with `--profile telegram` and confirmed it
  idles politely without a token — behavior correct, not a bug.
- CI workflow present at `.github/workflows/ci.yml` (backend lint/audit/
  test, frontend audit/lint/typecheck/test/build, compose-config jobs).
- Line-ending audit: `git ls-files --eol` — every indexed text file is
  `i/lf`. One working-tree-only CRLF (`frontend/package.json`, written by
  pnpm on Windows) was converted to LF in the working copy;
  `git add --renormalize .` produced **zero index changes**, so no
  renormalization commit was needed.
- Manual negative/malformed-input QA: per the decision above, owned by the
  user outside Claude Code.

**Phase 0 is signed off complete.** Only intentional deferrals remain
(fonts/logo/tagline → Phase 1; installers → Phase 6; first Alembic
revision → Phase 1) — all logged above.

---

## Phase 1 — Thin end-to-end slice (2026-07-16)

### Architecture decisions

**Auth token model: short-lived JWT access token (15 min, HS256) in the
JSON body + opaque rotating refresh token (7 days) in an HttpOnly cookie
scoped to `/api/auth`.** The SPA holds the access token in module memory
only — never localStorage — so a script-injection bug cannot exfiltrate a
persistent credential. Refresh tokens are 256-bit random strings; only
their SHA-256 lands in the DB (`refresh_tokens.token_hash`), so a DB
leak yields nothing replayable. Every refresh rotates the token and
records `replaced_by`; presenting a rotated/revoked token is treated as
evidence of theft and revokes the user's entire outstanding token family.
Login runs an Argon2id verify against a dummy hash when the email is
unknown so response timing doesn't reveal which accounts exist.

**Refresh must be single-flight on the client.** Direct consequence of
rotation-with-reuse-detection: two concurrent 401-triggered refreshes
would present the same cookie twice — the second one *is* "reuse of a
rotated token" and nukes the session. The API client shares one in-flight
refresh promise across all callers (concurrent data queries, the
boot-time silent refresh, React StrictMode's double-mounted effects).
This wasn't theoretical: the site-detail page fires two queries in
parallel, and after token expiry the pre-fix behavior logged the user
out. Regression-tested in `frontend/tests/api.test.ts`.

**Baselines are trust anchors; scans are observations.** A baseline
capture that comes back with HTTP ≥ 400 is refused and marked failed —
storing a 503/404 page as "trusted" would make the next identical error
page compare as *clean* (found live against an httpbin 503 during this
phase's stack verification). A *scan* that fetches an error page, by
contrast, completes normally and flags the change — that's a legitimate
observation of the site's current state.

**In-flight rows must be un-stickable.** Three layers guarantee a
baseline can never sit in `pending`/`capturing` (nor a scan in
`pending`/`running`) forever, which would 409-block
rebaseline/scan-now for that site permanently:
1. Expected failures (unreachable, timeout, SSRF-blocked) are caught in
   the task body and mark the row failed with a user-safe message.
2. Unexpected exceptions (disk full, DB blip, soft time limit) are caught
   by the Celery task wrapper, which best-effort marks the row failed —
   and only if it's still in-flight (a finished row is never overwritten).
3. If the worker died too hard even for that (SIGKILL, lost enqueue), the
   API treats in-flight rows older than 10 minutes (Celery hard limit is
   240 s) as abandoned: rebaseline/scan-now fail the stale row and
   proceed instead of 409ing.

**One-current-baseline is a DB invariant, not just app logic.** Partial
unique index on `baselines(site_id) WHERE is_current` (works on both
Postgres and SQLite via per-dialect `where` kwargs) backstops any race
between concurrent capture tasks; the capture transaction demotes the old
current and promotes the new one atomically.

**API process never imports worker code.** Playwright and friends stay
out of the FastAPI image; tasks are dispatched *by name* through a
broker-only Celery client with fail-fast transport options — Redis being
down surfaces as HTTP 503 with a clear message, never a hung request or a
silently dropped task. Worker-side, each task run builds and disposes its
own async engine because task bodies run under a fresh `asyncio.run()`
event loop each time (an engine cannot be shared across loops).

**SSRF policy is default-deny with a per-site opt-in (§9).**
`app/ssrf.py` refuses non-http(s) schemes, credential-bearing URLs,
oversized URLs, and any host resolving to a non-global address
(`is_global` covers RFC1918/loopback/link-local/ULA/CGNAT/reserved in one
property; multicast is checked separately since 224/4 reports
`is_global=True`). `sites.allow_private_networks` relaxes only the
address-range checks — never schemes or credentials. Validation runs at
site creation (immediate user feedback; in a worker thread so the DNS
resolution can't block the event loop) and again in the worker
immediately before every fetch, and the fetcher re-validates the *final*
URL after redirects so a public site redirecting to an internal address
is refused. Known limitation, deliberately deferred to the Phase 5
hardening pass: check-time and fetch-time DNS are separate resolutions,
so a fast-flipping record (rebinding) could pass validation and resolve
privately at fetch; closing it fully needs pin-the-IP transport.

**Playwright navigation waits on `load`, not `networkidle`** —
Playwright's own docs discourage `networkidle`, and any page with
long-polling or analytics beacons never goes idle (guaranteed 45 s
timeout). A fixed 2 s settle window after `load` lets late JS DOM writes
land before capture. Content is normalized (line endings, trailing
whitespace) before SHA-256 so representation noise doesn't flag; the
normalization is deliberately conservative — dynamic-content false
positives are for suppression rules (Phase 3), not for hashing less.

**SPA fallback must not swallow API 404s.** The `app` container serves
the built frontend with an index.html fallback for client-side routes,
but unmatched `/api/*` paths stay real JSON 404s — a typo'd API call
returning 200 text/html masks bugs badly (and Starlette normalizes paths
with `os.path.normpath`, so the guard normalizes `\` → `/` to behave
identically on Windows dev machines).

**Identity/branding:** tagline chosen — **"The watch that never stands
down."** (candidates considered: "Vigilance for every deployment",
"Your site's standing guard"). Ward mark drawn as a single even-odd
SVG path: a shield silhouette containing a negative-space keyhole/
sentinel figure, monochrome white-on-black, legible 16 px → 512 px;
exported to PNG (16/32/48/256/512) and multi-size `.ico` for the
Phase 6 Windows shortcut. Fonts wired per §4 substitutions via
Fontsource packages: Fraunces (display serif, `opsz` 144 + ss01),
Instrument Sans (display-lg/subtitle/body-md lane, with the −0.5%
tracking compensation the design doc mandates for ABC Favorit
substitutes), Inter (UI lane), Geist Mono (code, unchanged). Lane
discipline from the design doc is enforced by the `@utility` classes in
`index.css` — components use role utilities, never raw font families.

### Version verification log (all checked against live registries 2026-07-16)

New backend dev deps (PyPI): aiosqlite 0.22.1 · greenlet 3.5.3 (both for
the in-memory async-SQLite unit-test backend; no Postgres needed on the
host to run tests).

New frontend deps (npm): @fontsource-variable/fraunces 5.2.9 ·
@fontsource-variable/instrument-sans 5.2.8 · @fontsource-variable/inter
5.2.8 · @fontsource/geist-mono 5.2.8 · radix-ui 1.6.2 (unified package,
per current shadcn/ui guidance) · class-variance-authority 0.7.1 ·
clsx 2.1.1 · tailwind-merge 3.6.0 · sonner 2.0.7 · tw-animate-css 1.4.0.

Everything else runs on the Phase 0 locks, unchanged.

### What was built

**Database (first Alembic revision, `76f6f5dcf922`):** `users` (role
enum admin/analyst/viewer from day one — enforcement is Phase 5),
`refresh_tokens` (hash-only storage, rotation lineage via `replaced_by`),
`sites` (with the §9 `allow_private_networks` opt-in), `baselines`
(status machine pending→capturing→ready/failed, partial-unique
`is_current`, `capture_meta` JSON), `scans` (status + verdict enums,
`layer_scores` JSON dict that layer 1 populates now and layers 2–9 extend
in Phase 2 without a schema change). JSONB on Postgres / JSON on SQLite
via `with_variant`; enum *values* (not Python member names) stored via
`values_callable`. Downgrade path drops the Postgres enum types
explicitly (autogenerate forgets them). `alembic/env.py` wired to
`Base.metadata` for autogenerate.

**Backend API:** `/api/auth/login|refresh|logout|me` (full rotation +
reuse-revocation semantics above); `/api/sites` CRUD; site detail with
current-baseline summary (falls back to the newest attempt so
pending/failed captures are visible); `/api/sites/{id}/rebaseline` and
`/scan-now` (202 + enqueue, 409 on genuine in-flight, stale-row
recovery); `/api/sites/{id}/scans` (last 50); `/api/artifacts/...`
screenshot endpoints (auth-required; paths come only from DB rows and are
additionally resolved-and-confined to the artifacts root). All endpoints
in OpenAPI (asserted by a test). `app/seed_admin.py` seeds the first
admin from `ADMIN_EMAIL`/`ADMIN_PASSWORD` (min 12 chars), idempotent,
only resets a password when `ADMIN_RESET_PASSWORD=true`.

**Worker:** `wardress.capture_baseline` and `wardress.run_scan` Celery
tasks (async bodies under `asyncio.run`, per-run engine); Playwright
fetcher (Chromium headless, 1366×900, 45 s nav / 30 s screenshot
timeouts, 10 MB HTML cap, full-page PNG, curated response-header subset);
artifact store writing `page.html` + `screenshot.png` under
`<root>/<kind>/<id>/` with volume-relative paths in the DB (the volume
can move without a migration); layer-1 hash diff returning the §5
`{score, evidence}` shape.

**Frontend:** login page (glow-anchored card per the design doc's
elevation rules), app shell (64 px nav bar, hairline border, wordmark +
status + sign-out), sites list (status dots, polling every 3 s only
while a capture is in flight), add-site dialog (URL/name validation
surfaced inline, private-network opt-in checkbox), site detail
(baseline card, scan table polling every 2 s only while a scan is in
flight, rebaseline + scan-now buttons that disable according to state),
delete with confirm. TanStack Query for all server state; auth context
does a boot-time silent refresh so a page reload keeps the session.
shadcn/ui components (button, badge, card, dialog, input, label, table,
sonner) all fully reskinned against the design tokens — hairline borders
instead of shadows, accent colors as text/wash only (badge threat states
use glow-strength washes, never solid fills), true-black canvas, one
white primary button per viewport. `tsconfig` path alias `@/*` without
`baseUrl` (deprecated in TS 6+).

### Verified working (not just "should work")

Automated: backend **112/112** pytest (auth flow incl. rotation, reuse
revocation, expired tokens, deactivated users; site CRUD validation;
SSRF matrix; hashing/normalization incl. non-UTF8 and 5 MB inputs;
worker task state machines incl. idempotent redelivery, error-page
refusal, never-stuck guarantees; artifact serving incl. root
confinement; SPA-vs-API routing; OpenAPI completeness). Frontend **8/8**
vitest (login rendering, single-flight refresh under concurrent 401s,
session-expiry propagation, error shaping, 204 handling). `ruff check` +
`format --check` clean, `tsc -b` clean, oxlint 0 errors (3 pre-existing
fast-refresh warnings in shadcn-style files, non-blocking), `pnpm build`
clean.

Live compose stack (rebuilt from the fixed code): migration at head;
admin seeded; login → `/me` round-trip; site created via API → baseline
`pending → capturing → ready` (worker → Playwright → Postgres →
artifacts volume); `scan-now` → 202, duplicate scan-now → 409, scan
`running → completed / clean / layer1 score 0.0`; dynamic-content site
(httpbin/uuid) correctly produced hash mismatch evidence end-to-end;
Example-404 page → baseline refused with the HTTP-status message;
httpbin 503 → capture failed cleanly with a user-safe error (that
endpoint stalls, so it exercised the nav-timeout path); baseline and
scan screenshots served as image/png with auth, 401 without; unknown
`/api/*` → JSON 404 while `/sites/<id>` deep link → SPA 200; SSRF 422
with actionable detail on a private-range URL at creation time;
cookie-level refresh rotation verified with curl cookie jars (refresh
200 → old cookie 401 → successor also 401 because reuse revoked the
family). Worker logs show zero unexpected errors after the fixes.

### Incidents & resolutions (found during this phase's QA pass)

1. **Concurrent-refresh logout (frontend).** Two parallel queries hitting
   401 both called `/api/auth/refresh`; the second presented the
   just-rotated cookie and tripped the backend's reuse detection,
   revoking the whole token family and logging the user out. Fixed with
   a shared single-flight refresh promise used by both the 401-retry
   path and the boot-time silent refresh. Regression test added.
2. **Error pages could become trusted baselines (worker).** Found live:
   an httpbin 503 page was captured as a `ready` baseline, and a later
   scan of the same broken endpoint compared *clean*. Baselines now
   refuse HTTP ≥ 400 responses with a clear error; scans still complete
   on error pages (they're observations). Tests added for both halves.
3. **Rows could stick in-flight forever (worker + API).** An unexpected
   task exception (or a SIGKILLed worker) left baselines in `capturing`
   forever, and the 409 in-flight guards then blocked
   rebaseline/scan-now permanently. Fixed with the three-layer guarantee
   described in the decisions section. Tests added (wrapper catch-all,
   finished-rows-never-overwritten, stale-row API recovery).
4. **SPA fallback swallowed API 404s (app).** `GET /api/typo` returned
   200 + index.html instead of a JSON 404. Fixed in `SPAStaticFiles`
   with a path guard (plus `\`→`/` normalization because Starlette
   normpaths with the OS separator on Windows). Test initially still
   failed on Windows until the separator fix — that's why the guard
   normalizes.
5. **Blocking DNS in the event loop (API).** `assert_url_allowed` calls
   `getaddrinfo`; on a slow resolver that stalls every request on the
   loop. Site creation now runs the check via `asyncio.to_thread`.
6. Minor: `deps.py` missed `TypeError` when the JWT `sub` claim is a
   non-string (now 401, not 500); site-detail scans query had no error
   branch (spinner forever on failure — now shows an error line); a
   security test signed with a 17-byte HMAC key and warned (lengthened).

### Deliberate deferrals (not bugs)

- **DNS pin-the-IP transport** for the rebinding edge → Phase 5
  hardening (documented in `app/ssrf.py`'s docstring).
- **Artifact files of deleted sites** are left on the volume (DB rows
  cascade); a janitor task lands in a later phase — files are small and
  harmless meanwhile.
- **Rate limiting on auth endpoints** (§9 per-user/per-IP) → Phase 5
  hardening pass alongside the rest of the rate-limit work.
- **`cookie_secure` defaults false** (localhost self-hosted HTTP);
  Phase 6 installer docs will cover fronting with HTTPS and flipping it.
- **RBAC enforcement** — roles exist in the schema/JWT but every
  authenticated user currently sees everything; enforcement is Phase 5
  per the roadmap.
- **Scan history pagination** — `/scans` returns the latest 50; real
  pagination when the dashboard grows a history view (Phase 3).
- The 3 oxlint fast-refresh warnings in shadcn-pattern files (component +
  variant export in one file) are accepted as-is — that's the upstream
  shadcn layout.

---

## Phase 2 — Full detection engine (2026-07-16)

### Architecture decisions

**Layers are pure functions over plain data; the pipeline owns gating.**
Every layer is `(baseline: PageData, current: ScanPageData) -> {score:
0-1, evidence: dict}` in `worker/detection/` — no ORM rows, no network
handles, no gate logic inside layers. That keeps each one independently
testable (63 layer/fusion/pipeline unit tests run without a DB or
browser). Gating lives in `pipeline.py`: an identical layer-1 hash skips
layers 2/3/4/5/8 (byte-identical content cannot differ structurally,
visually, or semantically — and rendering noise in a re-screenshot is
exactly the false-positive class the gate suppresses); layers 6
(metadata) and 7 (cloaking) always run because TLS/header downgrades and
per-UA divergence are invisible to the primary content hash. Every skip
is recorded as a `scan_findings` row with `skipped=true` and the reason
(§5's "always log that the layer was skipped and why"). Each layer is
also crash-isolated: an unexpected exception becomes a skip-with-error
finding and the other layers still run (rule 6).

**Findings are rows, not JSON blobs.** `scan_findings` (scan_id, layer
1-9, layer_key, score, skipped, evidence JSONB) with a unique
(scan_id, layer) index — acks_late redelivery upserts (delete+rewrite in
the same txn), never duplicates. `scans.layer_scores` stays as a compact
`{key: {score, skipped}}` summary for the scan table; full evidence
comes from `/api/sites/{id}/scans/{scan_id}` for the Phase 3 drilldown
UI. The fused risk got its own indexed `scans.risk_score` column
(dashboard filtering/thresholding — never buried in JSON), per the
Phase 1 plan.

**Fusion (layer 9): seed-fitted logistic regression, not a hand-tuned
weighted sum.** No labeled scan history exists at install time, so the
scikit-learn LogisticRegression is fitted at first use on ~25 seed
scenario vectors (clean rescans, dynamic noise, benign deploys and
redesigns, cert rotations, full/stealth/signature/cloaking/semantic/
visual defacements) encoding the same domain knowledge a weighted sum
would — but producing calibrated probabilities and a drop-in upgrade
path: retrain on real labeled rows (then gradient boosting, §5) without
touching the pipeline. Fit is deterministic (fixed seeds, lbfgs, C=50 —
C swept explicitly; low C over-regularized the separation until benign
deploys crossed 0.5). Verified calibration: benign scenarios ≤ 0.26,
hostile ≥ 0.73, default threshold 0.5 in the gap. Skipped layers enter
the feature vector as 0.0 with a `layers_ran` mask in evidence. A model
failure degrades to max-sub-score with a note — fusion can never crash a
scan.

**Layer 7 compares raw-vs-raw, never rendered-vs-raw.** The metadata
prober (`worker/probe.py`, httpx) fetches the page under three UAs —
desktop Chrome (reference), Googlebot, mobile Safari — and layer 7
compares rotated UAs against that raw reference. Comparing against the
Playwright-rendered DOM would false-flag every JS-heavy site. Bot
blocking (non-2xx for a crawler UA) is recorded as evidence but scores
zero — it is common and legitimate, not cloaking. Divergence is
token-set Jaccard on visible text with a soft knee at 0.5 (Jaccard
exaggerates small edits on short pages — found by a unit test, knee
raised from 0.25).

**TLS probing observes, it doesn't judge.** `probe_tls` handshakes with
CERT_NONE and parses the DER via `cryptography` — an expired or
self-signed cert must still be *captured* (its weirdness is layer-6
evidence), not cause the probe to see nothing. Same philosophy for the
probe's httpx client (`verify=False` with an S501 waiver comment):
layer 6 must keep seeing sites whose TLS just broke. Fingerprint change
with same issuer+subject scores 0.1 (routine reissue); with a different
issuer/subject 0.55; expiry 0.5; each removed security header 0.3.
Headers *appearing* score zero — improvements are not threats.

**Header comparison is full-map-vs-full-map or nothing.** The Playwright
fetcher keeps its curated 4-header subset (Phase 1 shape, unchanged);
layer 6 only compares the probe's full header captures. If either side
lacks probe headers (probe degraded, or a Phase 1-era baseline), the
header comparison is skipped with a note — comparing full-vs-subset
would report every security header as "removed". (Found in this phase's
QA pass — see incidents.)

**Signature/semantic layers match on NEW text only.** Layers 5 and 8
diff visible text (lxml text nodes minus script/style) against the
baseline and run their regex/lexicon passes on sentences that weren't
there before — a security blog whose baseline already discusses
defacement can't flag on every rescan. Script-mixing detection (layer 5)
buckets alphabetic chars by Unicode-name prefix and only fires when a
clear dominant script (≥60%) flips to a different clear dominant script.

**MiniLM is baked into the worker image at build time** (`HF_HOME`
download in Dockerfile.worker, after the dependency layer, before source
copy). A scan must never depend on a HuggingFace download at runtime —
self-hosted installs may be offline. If the bake fails the build
proceeds with a warning and layer 8's embedding feature degrades to None
at runtime (logged, never crashes). Embedder is process-cached, CPU
pinned (`device="cpu"`).

**Beat stays dumb; adaptive state lives in the DB.** One fixed 60 s
periodic task (`wardress.dispatch_due_scans`) polls
`sites.next_scan_at <= now` (indexed) and enqueues due scans — so a Beat
restart loses nothing, and the "single scheduler instance" rule from the
Celery docs is trivially satisfied. The dispatcher applies exactly the
API's semantics via the shared `app/scanning.py` policy module: genuine
in-flight scan -> skip without creating a row (the 409 rule — no
pile-up); stale in-flight (>10 min) -> fail it and proceed (the Phase 1
three-layer never-stuck guarantee, now shared); no ready baseline ->
skip. `next_scan_at` advances *before* enqueue, so a crash or lost
enqueue delays a site by one interval instead of tight-looping it; the
tick is capped at 50 dispatches (backlog drains over subsequent ticks);
the periodic task carries `expires=2 ticks` so a Redis backlog cannot
burst-fire stale ticks; a DB outage fails the tick gracefully and Beat
keeps ticking.

**Adaptive cadence tightens on *material* change (risk ≥ 0.15), not on
any nonzero score.** A dynamic page whose hash flips every scan (~0.03
risk) must relax back to its base cadence, or "adaptive" would mean
"permanently tightened". Change -> base/4 (floor 5 min); each stable
scan -> ×1.5 back toward base (cap 24 h). Verified live: flagged scan
took 60 min -> 15 min; next clean scan relaxed 15 -> 22 min. Scan
completion reschedules adaptively in the task; the dispatcher's advance
is the safety net for scans that never complete. Changing the base
interval via PATCH resets adaptive state (the user asked for that
rhythm; honor it).

**Verdict vocabulary grew: clean | changed | flagged | error.**
`changed` = differences exist but fused risk is below the site's
threshold; `flagged` = risk ≥ threshold (needs attention). Postgres enum
extended with ALTER TYPE ADD VALUE; the downgrade path rewrites flagged
-> changed and rebuilds the type (documented in the migration).

**Celery time limits raised 180/240 -> 300/360.** A Phase 2 scan runs
fetch + probe + nine layers + MiniLM inference. Still well under the
10-minute stale cutoff (now shared in `app/scanning.py`). Detection runs
in `asyncio.to_thread` so the CPU-bound layers don't stall the task's
event loop.

### Version verification log (checked against live registries 2026-07-16)

No new packages needed — every Phase 2 library (lxml 6.1.1,
scikit-image 0.26.0, imagehash 4.3.2, sentence-transformers 5.6.0,
scikit-learn 1.9.0, httpx 0.28.1) was already pinned and locked in
Phase 0. pillow 12.3.0 and numpy 2.5.1 were *promoted from transitive to
direct* dependencies (the detection layers import them directly; a
transitive drop must not break us silently) — both verified current on
PyPI 2026-07-16, lockfile resolution unchanged (150 packages), zero
nvidia entries, torch still 2.13.0+cpu (verified live in the worker:
`torch.cuda.is_available() == False`). pip-audit: no known
vulnerabilities. Docs re-read this phase: lxml parsing/HTMLParser
recovery semantics (fetched fresh into docs-cache/lxml-parsing.html +
lxml-html.html), scikit-image SSIM data_range warning (cache), imagehash
usage + hex_to_hash (cache), sentence-transformers v5 quickstart
(cache), scikit-learn LogisticRegression/predict_proba (fetched fresh
into docs-cache/sklearn-logreg.html), Celery Beat entries/crontab/
single-scheduler rule (cache). WebFetch tooling was again unavailable
(Phase 0 incident repeated); curl into docs-cache/ used instead.

### What was built

**Schema (Alembic `b41c7a9e2d05`):** `scan_findings` (unique
(scan_id, layer), JSONB evidence, CASCADE delete); `scans.risk_score`
(indexed float); `sites.flag_threshold` (default 0.5),
`auto_scan_enabled` (default true), `scan_interval_minutes` (default
60, clamp 5-1440), `current_interval_minutes` (adaptive state),
`next_scan_at` (indexed, the dispatcher's poll target); scan_verdict
enum + 'flagged'. Downgrade path tested live (downgrade -> upgrade
round-trip on the compose Postgres).

**Detection engine (`worker/detection/`):** types.py (PageData/
ScanPageData/UAVariant, layer_result/skip_result helpers), dom.py
(layers 2+3: recovering lxml parse, tag-tree stats with weighted
script/iframe/hidden attention, reference-set diff with new-external-
domain weighting, evidence capped at 50 items/list), visual.py (layer
4: SSIM at bounded compare size with explicit data_range, 16×16
pHash+dHash, shared-top-region crop for legitimately-grown pages,
decompression-bomb guard kept), signatures.py (layer 5: weighted
strong/medium/weak defacement-phrasing regexes, profanity burst,
Unicode-script-flip detection, new-text-only matching), metadata.py
(layer 6: TLS fingerprint/issuer/expiry diff, security-header removal/
weakening, robots.txt diff, full-map-or-skip rule), cloaking.py (layer
7: raw-reference UA comparison, bot-blocking-is-not-cloaking),
semantics.py (layer 8: aggression lexicon + topic keywords on new text,
MiniLM cosine drift, Gemini/Ollama escalation hook documented as Phase
4), fusion.py (layer 9 as above), pipeline.py (ordering, gating, crash
isolation, degraded-baseline handling).

**Worker:** `probe.py` (TLS/robots/headers/UA-rotation prober, every
sub-probe individually fail-safe, SSRF-validated including
per-redirect-hop re-validation via httpx event hook); `scan_tasks.py`
extended (baseline capture stores probe metadata in capture_meta; scan
runs probe + nine layers in a thread, persists findings idempotently,
computes verdict vs per-site threshold, reschedules adaptively);
`beat_tasks.py` (the dispatcher); artifact read helpers with root
confinement.

**API:** `PATCH /api/sites/{id}` (threshold/interval/auto-scan, with
the adaptive-state-reset semantics); `GET /api/sites/{id}/scans/
{scan_id}` (scan + ordered findings — the Phase 3 drilldown contract);
site create/list/detail responses carry the new fields; scan responses
carry risk_score. OpenAPI completeness test extended.

**Frontend (minimal per roadmap — full SOC dashboard is Phase 3):**
site-detail Monitoring card became a settings card (threshold %, base
interval, auto-scan toggle, next-scan display; design-token styling);
scan table shows verdict (flagged=red badge, changed=orange), risk %,
layers-ran summary; api.ts typed for all new fields/endpoints.

**Tests: 216 backend (was 112) + 8 frontend.** New: 30 layer tests
(2-5), 34 metadata/cloaking/semantics/fusion/pipeline tests, 9 probe
tests (httpx MockTransport — request handling only, no live traffic),
17 scheduler tests (adaptive policy + dispatcher semantics incl.
in-flight skip, stale recovery, enqueue failure, DB outage, per-tick
cap), 14 Phase 2 API tests (settings validation, findings drilldown,
cross-site 404, cascade). All ruff/format clean; tsc/oxlint/vitest/
build clean.

### Verified working (not just "should work")

Live compose stack, rebuilt from final code, migration at head:
- example.com scanned through the full engine: layer 1 identical ->
  layers 2/3/4/5/8 skipped with logged gate reason, layers 6/7/9 ran
  (TLS fingerprint captured with real expiry date; googlebot +
  mobile_safari variants both 200 with similarity 1.0), risk 0.035,
  verdict clean. All nine findings rows stored with evidence.
- Deliberately changed page flagged with correct per-layer evidence: a
  local test page (private-network opt-in) was baselined, then replaced
  with defacement-style content (signature phrases, new external
  script + hidden iframe domains, black/red visual). Scan verdict
  **flagged**, risk 0.9999: L2 0.878 (script/iframe/hidden counts 0->1
  each), L3 0.835 (evil-cdn.example.net in added_new_domains for both
  script and iframe), L4 0.889 (SSIM 0.0, pHash distance 144 bits),
  L5 1.0 (matched "HACKED BY", "gr33tz", "We are legion", "Expect us",
  "Your security was weak"), L8 0.926 (real MiniLM inference in the
  container: semantic similarity 0.063; topic hit contact_defacer),
  L6/L7 correctly 0.0 (same server, no cloaking).
- Adaptive scheduling observed live: flagged scan tightened 60 -> 15
  min and set next_scan_at; page restored + site forced due -> Beat
  tick dispatched exactly one scan ({'due': 1, 'enqueued': 1}), verdict
  clean, cadence relaxed 15 -> 22 min. Dispatcher ticks run every 60 s
  in the worker (logs confirm) and no-op cleanly when nothing is due.
- Migration downgrade -> upgrade round-trip clean on live Postgres;
  scan_findings table shape verified via psql (JSONB, unique index,
  CASCADE FK).
- torch 2.13.0+cpu inside the worker container, cuda unavailable; MiniLM
  loads from the baked HF_HOME cache (no runtime download).
- SPA still served, unknown /api/* still JSON 404, auth flow unchanged
  (all 112 Phase 1 tests still pass).
- Test sites deleted after verification (cascade removed scans and
  findings); local test server stopped.

### Incidents & resolutions (found during this phase's QA pass)

1. **Layer 6 header comparison could false-positive against degraded or
   Phase 1-era baselines.** The baseline reader fell back from the
   probe's full header map to the fetcher's curated 4-header subset;
   comparing full-vs-subset would report every security header as
   "removed" (0.3+ each). Fixed: layer 6 compares full-map-vs-full-map
   or skips with a note; the scan side no longer falls back to the
   curated subset either. Regression test added.
2. **Fusion under-separated with C=2.0.** Default-ish regularization
   squashed the seed scenarios: benign deploy scored 0.505 — over the
   default 0.5 flag threshold. Swept C explicitly (5/10/20/50), added a
   heavy-but-benign "site redesign" seed row, settled on C=50: benign
   ≤ 0.26, hostile ≥ 0.73. Calibration assertions are unit-tested so a
   future seed edit that breaks separation fails CI.
3. **Layer 7's divergence knee was too low.** Token-set Jaccard
   exaggerates small edits on short pages: one dynamic "Visitor #42"
   line produced divergence 0.4 -> score 0.2. Unit test caught it; knee
   raised to 0.5 (soft ramp to 1.0 above it).
4. **Visual layer carried dead padding code.** The pad-with-white branch
   was unreachable (both arrays were already cropped to the shared
   height); removed, and the crop-top-region semantics documented
   honestly instead of the misleading "pad" comment.
5. **Scheduling would have tightened on *any* nonzero layer score**
   (including a 0.03-risk dynamic-content hash flip), permanently
   pinning dynamic sites at minimum interval. Changed to a
   MATERIAL_CHANGE_RISK=0.15 floor before tightening; tests added.
6. **CRLF regressions** in files edited via shell heredocs on Windows;
   swept all source trees back to LF (Phase 0 line-ending rule).

### Deliberate deferrals (not bugs)

- **Gemini/Ollama escalation for layer 8's ambiguous band** -> Phase 4
  (per the kickoff's "only if natural" — the local pass is complete and
  the escalation hook is documented in evidence as "not configured").
- **Fusion retraining on real labeled history + gradient boosting
  upgrade** -> once per-site verdict history accumulates (§5's
  documented upgrade path; the feature order is fixed and stored per
  finding for compatibility).
- **Multi-region cloaking fetch via user proxy nodes** (§5 optional) ->
  needs the proxy-node settings UI; evidence notes it as not configured.
- **Suppression rules (css/regex/bbox)** -> Phase 3 per roadmap (the
  point-and-click UI); layer evidence already carries the diffs the UI
  will need.
- **Findings drilldown UI** -> Phase 3 (the API contract + data are
  live; the site-detail table shows summary scores only).
- **DNS pin-the-IP** (Phase 1 deferral) still Phase 5; the probe reuses
  the same assert-then-fetch pattern including per-hop redirect
  re-validation, so its exposure equals the fetcher's.
- **Beat tick observability** (queue depth, last-dispatch age on
  /api/health) -> Phase 5 health page.
- The probe intentionally keeps `verify=False` (observation, not trust —
  S501-waived with rationale); revisit only if a user-facing "strict
  TLS" toggle appears.

---

## Phase 3 — SOC Dashboard UI (2026-07-17)

### Architecture decisions

**Suppression rules are per-site DB rows applied inside the detection
pipeline, before the content layers — never a post-hoc score filter.**
`suppression_rules` (Alembic `d7e3a1c40f88`: site_id FK CASCADE, type
enum css_selector/regex/bbox, value, note, created_at) feed
`worker/detection/suppress.py`, which builds one validated bundle per
scan: css_selector rules strip matching subtrees from BOTH baseline and
current documents before layers 2/3/5/8 see them; regex rules strip
matching text spans from both sides' visible text; bbox rules mask
screenshot regions on both images before layer 4. Filtering both sides
symmetrically is the invariant — filtering only the current side would
report the baseline's copy of the ignored element as "removed" on every
scan. Layer 1 always hashes the ORIGINAL content: the hash is the
tamper-evidence anchor, and a suppressed scan of identical bytes must
still say "bytes identical", while a changed-but-suppressed scan says
"bytes differ, content layers explain why it's fine". Every application
of suppression is recorded in evidence (`suppression_applied` per
content layer, `suppressed_regions` on layer 4, a `suppression` summary
on fusion), so the drilldown UI can always show *why* a change didn't
count. Rules that fail to parse (bad selector/regex/bbox) are skipped
and surfaced in evidence as `unusable_rules` — a typo'd rule degrades to
"not applied and visibly reported", never to a crashed scan (rule 6).

**bbox coordinates are fractions of the BASELINE capture the user drew
on.** Value format `"x,y,w,h"`, each 0-1, validated server-side (422 on
out-of-range/malformed). The visual layer resolves the fractions against
the baseline's pixel geometry and carries the mask onto the current
capture scaled through the *width ratio only* — so when a later capture
is taller or shorter (content added below), the mask stays anchored over
the same page content instead of drifting proportionally down the page.
This replaced an initial height-relative design after QA found the
drift; the regression test pins the semantics (change below a
full-width top-half mask on a 2x-taller capture must still register).
The RegionPicker measures drag coordinates against the inner
full-image-height content element, not the scrollable wrapper, so
fractions stay correct when the screenshot is scrolled mid-drag.

**HTML snapshots are served as `text/plain; charset=utf-8`, never
text/html.** The DOM diff tree needs the raw captured HTML client-side,
but captured pages are untrusted content — serving them as text/html
from the dashboard origin would execute a defaced page's scripts inside
the authenticated SPA. The frontend parses the text response with
DOMParser, which produces an inert document (no script execution, no
resource fetching). Same auth + artifact-root confinement as the
screenshot endpoints.

**All artifact fetches go through an authenticated blob helper, not
`<img src>`.** Artifact endpoints require Bearer auth, and the token
lives in module memory only (Phase 1 decision), so plain `src` URLs
can't work. `artifactFetch` adds the Authorization header, retries once
through the single-flight refresh on 401, and hands back object URLs
(`useArtifact`) or text (`useTextArtifact`) with revocation on unmount.

**DOM diff is a client-side custom renderer, no diff library.**
`buildDomDiff` parses both snapshots with DOMParser and pairs children
by a tag#id.class signature (first-unmatched-wins), marking nodes
same/added/removed/modified; removed baseline nodes render in place in
the tree. States render exactly per the design addendum: accent-green
left border + low-opacity wash for added, accent-red for removed —
washes, never solid fills. Changed paths auto-expand (depth-capped);
child lists cap at 120 with an explicit "N more" line rather than
silent truncation.

**Visual diff slider computes altered regions client-side from the two
screenshots** (24px luma-block grid, greedy rectangle merge) rather than
shipping a server-side diff image — the two PNGs are already being
fetched for display, and the overlay stays a translucent accent-red wash
(rgba 0.28 fill / 0.55 border) per the design rules. Different-height
captures are compared over the shared top region (crop, not squash —
squashing misaligned every block row, found in QA). Suppressed bbox
regions render as a distinct hatched overlay so "ignored" and "altered"
can't be confused. The divider is keyboard-accessible (role=slider,
arrow keys).

**Recharts is code-split.** `lazy()`/`Suspense` around the gauge and
timeline moved the ~254 kB chart chunk out of the main bundle; the
drilldown and site pages load it on demand. Gauge is a 270-degree
RadialBar arc on a hairline track, tone thresholds shared with the
table (red >= site threshold, orange >= 0.15 material-change band,
green below). Timeline is a time-scaled LineChart with per-scan verdict
dots, a dashed threshold ReferenceLine, and point-click navigation into
the drilldown.

**Scan history got real pagination** (Phase 1 deferral closed):
`GET /api/sites/{id}/scans?offset=&limit=` returns
`{items, total, offset, limit}` (limit <= 200, default 50, newest
first). The site page keeps a 20-row paged table and feeds the timeline
from a separate 200-scan window query, so paging the table doesn't
reshape the chart.

**Scan drilldown page renders evidence generically as a floor.** Each
of the nine layers has a purpose-built evidence renderer (hash pair, DOM
deltas, link/domain diffs, SSIM/pHash, signature matches with strength
badges, TLS/header diffs, per-UA similarity rows, semantics, fusion
per-layer bars) — but unknown evidence keys always fall through to a
key/value renderer, so a future layer change can't silently hide
evidence. Cards auto-expand when the layer scored >= 0.15.

### Version verification log

No new packages. Recharts 3.9.2, lucide-react, radix-ui — all already
pinned and locked since Phase 0/1; the chart work consumed the existing
lock. Docs consulted from docs-cache (Recharts RadialBar/LineChart,
Tailwind v4 @utility) plus the React 19 lazy/Suspense semantics already
cached. Lockfiles unchanged this phase (backend 150 packages, zero
nvidia entries; frontend lock untouched).

### What was built

**Schema (Alembic `d7e3a1c40f88`):** `suppression_rules` as above;
downgrade drops the table and the Postgres enum type.

**Backend:** suppression CRUD under `/api/sites/{site_id}/
suppression-rules` (list/create/delete; create validates selector
syntax via lxml.cssselect — imported lazily so the API image never
imports worker code — regex compilability, and bbox bounds, 422 with
actionable detail); scans pagination endpoint reshaped to `ScanPage`;
`SiteDetailOut.baseline_id` exposed (the drilldown needs the scan's
own comparison anchor); HTML artifact endpoints
(`/api/artifacts/baselines/{id}/html`, `/scans/{id}/html`) with the
text/plain rule; `worker/detection/suppress.py` + pipeline wiring +
`_mask_regions` baseline-anchored masking in visual.py; scan task loads
rules once per scan and passes the bundle through (a broken rule-load
degrades to an unsuppressed scan that still completes — tested).

**Frontend:** scan drilldown page (`/sites/:siteId/scans/:scanId`) —
verdict header explaining risk vs threshold, lazy risk gauge, in-flight
polling banner, visual diff slider + DOM diff tree side by side on xl,
nine finding cards; site page rewritten — paged scan table, lazy
incident timeline, suppression panel (rules list with human-readable
bbox descriptions, point-and-click RegionPicker over the baseline
screenshot with normalized-drag drafting and hatched existing rules,
CSS-selector and regex add forms, delete, "applies from the next scan"
toasts); `api.ts` grew the suppression/pagination/artifact surface;
`use-artifact.ts` hooks; `bbox.ts` shared parse/serialize;
responsive pass (mobile display-size clamps, 44px touch targets,
tightened shell padding at sm); token-purity fixes (dialog overlay
bg-canvas/70, no default-shadcn remnants; no emoji anywhere).

**Tests: 249 backend (was 216) + 17 frontend (was 8).** New backend:
suppression rule validation/CRUD/cross-site 404, builder semantics
(both-sides stripping, unusable-rule reporting), bbox baseline-anchor
regression, pipeline integration (stored rules end-to-end through
`_run_scan`, broken-loader fail-safe), HTML artifact auth/content-type/
404, pagination shape, OpenAPI completeness extended. New frontend:
DOM diff builder (identical/added/removed/modified/sibling pairing/
malformed input) and bbox round-trip/bounds/clamping.

### Verified working (not just "should work")

Live compose stack (images rebuilt, migration upgraded on Postgres):
- Local QA page baselined through the worker (`host.docker.internal`
  + per-site private-network opt-in). Identical-content scan: clean,
  risk 0.035, layers 2/3/4/5/8 gate-skipped.
- Page replaced with defacement-style content: **flagged, risk 0.9999**
  — L5 1.0 (five phrase matches incl. strong "HACKED BY"), L3 0.835
  (new external script+iframe domains listed), L2 0.878 (0 to 1
  script/iframe/hidden each), L4 0.832 (SSIM 0.12, pHash 166 bits),
  L8 0.953.
- All four drilldown artifact endpoints live: both screenshots
  image/png 200 with auth, 401 without; both HTML snapshots
  `text/plain; charset=utf-8` (script content present but inert).
- Pagination live: `?offset=0&limit=1` returns 1 item, correct total.
- Suppression end-to-end: page restored with only the visitor counter
  changed -> `changed`, risk 0.041; css_selector `#visitor-counter` +
  bbox rule created via the API the panel calls; heavy churn injected
  INSIDE the suppressed subtree (new script, iframe, link, external
  domain) -> **not flagged** (risk 0.052), layers 2/3/5 all 0.0,
  `suppression_applied` in layer evidence, bboxes+selectors echoed in
  fusion's `suppression` summary, `suppressed_regions` on layer 4.
- Negative control: real defacement replacing the page while rules
  were active -> still **flagged, risk 0.999** — suppression cannot
  blind the engine to changes outside the ignored region.
- Malformed rules rejected live with 422 (unclosed regex group,
  out-of-range bbox, invalid selector); rule delete works.
- Dashboard UI driven headlessly against the live stack (Playwright,
  19/19 checks): login -> site page (timeline chart drawn, suppression
  panel listing the selector rule, 5-row scan table) -> point-and-click
  bbox rule drawn on the baseline screenshot (drag -> toast -> appears
  in list) -> flagged-scan drilldown (Flagged badge, gauge, visual
  slider with a highlighted altered region, DOM tree showing
  added/removed nodes, all nine finding cards, matched "HACKED BY"
  phrase and evil.example.net domain visible in evidence). Full-page
  screenshot reviewed against DESIGN-resend.md: true-black canvas,
  hairline-bordered cards, wash-only accents, correct type lanes.
- QA site deleted afterwards (cascade removed scans/findings/rules);
  QA fixtures removed from the working tree.

Automated (final state): backend 249/249, frontend 17/17, ruff
check+format clean, tsc clean, `pnpm build` clean, oxlint 0 errors
(5 fast-refresh warnings in shadcn-pattern files, same accepted class
as Phase 1), all sources LF.

### Incidents & resolutions (found during this phase's QA pass)

1. **bbox masks drifted on captures of different heights.** The first
   implementation resolved y/h fractions against each image's own
   height, so a taller current capture pushed the mask down over
   different content — the mask no longer covered the element the user
   drew around. Redefined bbox as baseline-anchored (decisions above);
   `_mask_regions` takes the baseline as reference geometry; regression
   test with a 2x-taller capture added; frontend overlay rescales by
   the aspect ratio to match.
2. **RegionPicker coordinates were measured against the scrollable
   wrapper**, whose bounding rect moves as the user scrolls a tall
   screenshot — a drag after scrolling produced wrong fractions. Fixed
   by measuring against the inner content element (full image height).
3. **Visual-diff sampling squashed both screenshots to a fixed compare
   height**, misaligning every block row when heights differed and
   producing phantom "altered" regions. Fixed to aspect-preserving
   draw + shared-top-region compare, matching the worker's layer-4
   crop semantics; overlay regions rescale back onto the displayed
   capture.
4. **Docker Desktop daemon wedge during image rebuilds** (Windows):
   overlapping background `docker compose build` invocations produced
   zero output and even `docker ps` hung; resolved by stopping the
   hung builds and restarting Docker Desktop (user restarted the
   machine). Builds then completed normally. Process rule going
   forward: build images serially in the foreground, never overlap
   Docker builds in background tasks.
5. **Access token expired mid-verification** (15-min TTL, by design)
   — live-QA scripts now re-login instead of reusing a cached token.
   No product change; the SPA already handles this via the
   single-flight refresh.
6. Minor: `ruff format` re-run after heredoc-appended test code; a
   conditional assertion in a new scheduler-era test tightened to an
   unconditional one; two stale-file Edit misfires re-read and
   re-applied.

### Deliberate deferrals (not bugs)

- **Suppression rules apply from the next scan** — no retroactive
  re-evaluation of historical findings. Re-scoring old scans against
  new rules is a possible Phase 5+ nicety; the panel's toast states
  the semantics explicitly.
- **Regex rules operate on visible text**, not raw HTML — attribute
  churn (e.g. rotating CSRF tokens in hidden inputs) is covered by
  css_selector rules instead; documented in the panel's helper text.
- **Client-side altered-region detection is a viewer aid**, not the
  detection verdict — layer 4's SSIM/pHash in the worker remains the
  scored signal; the slider overlay is best-effort visualization.
- **Timeline windows the most recent 200 scans**; a date-range picker
  belongs to a future analytics pass if history depth demands it.
- **RBAC on suppression endpoints** — any authenticated user can
  manage rules until the Phase 5 role-enforcement pass (same standing
  deferral as all other mutating endpoints).
- The 5 oxlint fast-refresh warnings remain the accepted shadcn-layout
  class from Phase 1 (2 new files follow the same pattern).
- **Manual negative/malformed-traffic QA** against the running stack
  remains the user's sign-off step outside Claude Code, per the
  Phase 0 sign-off decision — unchanged for this phase.

---

## Phase 4 — Notifications & Intelligence (2026-07-17)

### Architecture decisions

**Every integration secret is encrypted at rest with Fernet and never
round-trips to the client.** `app/crypto.py` derives the Fernet key as
urlsafe-b64(SHA-256(`CREDENTIALS_ENCRYPTION_KEY`)) so the .env value can
be any string; `app/settings_store.py` stores SMTP/Telegram/Gemini/
Ollama configuration as encrypted JSON blobs in a new `app_settings`
table, and notification channels carry their own `config_encrypted`
column. GET endpoints return redacted hints only ("smtp.ex...",
"1234567890:AAAA...", key prefixes) plus `configured` flags; PUT uses
patch semantics where `None` keeps the stored secret and `""` clears it,
so editing a host never silently wipes a credential. A `DecryptionError`
(rotated key, corrupted row) is treated as "not configured" — surfaced
as a re-save prompt in the UI, never a crash.

**Alert delivery is a separate Celery task, never part of the scan
body.** A flagged `_run_scan` creates the `Alert` row (unique
`scan_id` — acks_late redelivery reuses it instead of duplicating) and
enqueues `wardress.deliver_alert`; the enqueue itself is wrapped so a
dead Redis at alert time logs and moves on — the scan verdict is already
committed and is never affected (rule 6). The delivery task resolves the
channel set (per-site channels plus global ones), writes one
`alert_deliveries` row per channel with status sent/failed/skipped and a
human-readable detail, and commits per channel so one slow SMTP server
cannot roll back another channel's outcome. Re-running the task skips
channels that already have delivery rows (idempotence guard). Mute is a
delivery-time decision: `sites.muted_until` in the future turns every
delivery into a recorded `skipped` row — scans, verdicts, and the alert
row itself continue unaffected, and the skips stay visible on the
Alerts page.

**One delivery primitive shared by real alerts and every test button.**
`app/alerting.py` exposes `send_email` (Jinja2 HTML template, CSS
inlined with premailer, sent via aiosmtplib with an SMTP error taxonomy
mapped to actionable messages) and `send_apprise` (tgram:// built from
the stored bot token + captured chat, or the raw user Apprise URL, 40s
timeout). Everything returns `(ok, detail)` instead of raising; the
worker records failures as delivery rows, the settings test buttons
show them verbatim. Channel creation validates the Apprise URL with the
same `apprise` library the delivery path uses — a channel that saves is
a channel that can send.

**The §8 "Send Test Email" button really gates Save.** The SMTP test
endpoint accepts optional inline settings (the unsaved form values;
omitted password falls back to the stored credential) so the test proves
the exact configuration about to be saved. The frontend disables Save
until a test against the *current* form values succeeds, and any edit
re-locks it. This replaced an initial test-after-save design the QA
pass caught as contradicting the master prompt.

**The Telegram bot is a real two-way python-telegram-bot v22 app in its
own container, with a manual PTB lifecycle.** `run_polling()` owns the
loop and only stops on process signals, so the bot instead drives
initialize/start/start_polling itself and re-reads the encrypted DB
settings every 60s — pasting a new BotFather token into Settings
restarts polling with it within a minute, no container restart. A
missing token idles politely; `InvalidToken` (revoked/mistyped) logs a
plain-language warning and retries on a 60s backoff — the container
never crash-loops and nothing in it can affect scanning. The first
/start captures that chat ID into settings (shown in the UI as
confirmation); every other chat is refused — one bot, one owner.
Commands: /status /sites /scan /ack /mute /explain /help, all wrapped in
an authorization + crash-isolation guard, all plain text (no markdown
parsing surprises from site names, no emoji). Outbound alert pushes go
through Apprise tgram://, not this bot — it is a control surface, not a
delivery path.

**LLM escalation can only raise a verdict, and only in the ambiguous
band.** `worker/llm_escalation.py` consults the configured provider
solely when fused risk lands in [0.35, 0.75) on a changed-but-not-
flagged scan; a malicious classification with confidence >= 0.6
upgrades changed to flagged and records the model's reasoning in the
layer-8 evidence (visible in drilldown and reports). Already-flagged
scans never spend an LLM call; a benign classification changes nothing
(the deterministic engine's verdict stands — the LLM is a tiebreaker,
never a veto). `escalate_scan` cannot raise: no key, rate limit, quota,
network failure, or garbage response all degrade to "no escalation"
with a status string in evidence. Gemini (`gemini-2.5-flash` via
google-genai) is preferred when both providers are enabled; Ollama
(OpenAI-compatible /v1) is the local fallback. `app/llm.py` enforces an
aiolimiter 8-requests/60s ceiling, a 200-call/day in-process budget,
and 3-attempt backoff on 429s.

**"Explain this incident" is one cached implementation with two
surfaces.** `app/explain.py` builds a compact incident-summary prompt
from the scan + findings, calls the same provider resolution as
escalation, and caches the result on the scan row
(`explanation`/`explanation_provider`/`explanation_at`). The dashboard
button and the bot's /explain both call it: same prompt, same cache
(force-regenerate available in the UI), same degradation — no provider
configured returns a clear "not configured" message, never a 500.

**PDF export is WeasyPrint rendered in a worker thread inside the API
process** — the Phase 0 WeasyPrint-over-Playwright rationale explicitly
includes "report rendering must work even if the browser pool is
saturated or wedged", so it must not queue behind scan jobs. The report
is a Jinja2 HTML template using CSS Paged Media (dark cover page,
running footer, numbered pages), screenshots embedded as data URIs read
strictly from within the artifacts root (path-confined; a missing file
degrades to a report without that image, never a failed export), and a
pre-rendered static SVG timeline (no live JS in a print pipeline). The
Markdown export shares the same `app/reporting.py` loader/formatting so
both formats describe a scan identically; a WeasyPrint failure returns
a 500 that names the Markdown export as the fallback. Evidence values
are capped before rendering so oversized blobs never leak into an
exported document. Report downloads in the SPA go through the
authenticated blob helper (Bearer header, filename parsed from
Content-Disposition).

### Features landed

Migration `e9a2b7c15f04`: `notification_channels`, `app_settings`,
`alerts` (unique scan_id), `alert_deliveries`, `sites.muted_until`,
`scans.explanation`/`explanation_provider`/`explanation_at`.
`worker/telegram_stub.py` deleted — replaced by the real bot container.

API: `/api/settings/{smtp,telegram,gemini,ollama}` GET/PUT + test
endpoints, `/api/notification-channels` CRUD + per-channel test,
`/api/alerts` (paginated, unacknowledged filter) + ack,
`/api/sites/{id}/scans/{id}/explain` (force flag),
`/api/reports/{scan_id}/{pdf,markdown}`; site PATCH gained
`mute_minutes` (0 unmutes, 7-day cap — same cap as the bot's /mute).

Frontend: new Settings page (channel presets ntfy/Discord/Slack/
webhook + Email + Telegram, scope all-sites/per-site, per-channel
test/disable/delete; SMTP card with test-gates-save; Telegram card with
the BotFather walkthrough and live /start chat-capture polling; Gemini/
Ollama card; secrets-at-rest note), new Alerts page (paginated feed,
per-delivery status rows, idempotent acknowledge, 30s refresh), nav
Sites / Alerts / Settings, scan drilldown gained PDF/Markdown export
buttons and the Explain card (cached text + provider/timestamp,
regenerate), site settings gained mute 1h/24h/unmute with the skipped-
delivery explanation. All on the design tokens; no emoji.

**Tests: 313 backend (was 249) + 19 frontend (was 17).** New backend
(64): crypto round-trip/rotation, settings-store patch semantics,
redaction (no secret ever appears in a GET body), channel validation
(bad Apprise URL, missing recipient, cross-type fields), SMTP error
taxonomy, delivery task (per-channel rows, mute -> skipped, idempotent
re-run, broken-channel isolation), alert-on-flagged integration (alert
row + enqueue, clean scan -> nothing, dead Redis never fails the scan,
redelivery no duplicate), escalation wiring (band boundaries, upgrade +
evidence, benign no-op, already-flagged short-circuit, exploding DB
degrades), explain caching/degradation, report loader/markdown/
filename/404s, inline-SMTP-test gating. New frontend: report download
carries the Authorization header + parses the server filename; fallback
filename when the header is missing.

### Verified working (not just "should work")

Live compose stack (all backend images rebuilt serially in the
foreground; `alembic upgrade head` applied e9a2b7c15f04):
- End-to-end alert chain with a real webhook receiver: local static
  site baselined, page replaced with defacement-style content,
  scan-now, **flagged at risk 0.99996**, alert row created,
  `wardress.deliver_alert` ran, delivery row `sent`, and the receiver
  logged the full Apprise JSON payload (title "Wardress alert: Phase4
  Verify flagged at 100% risk", top-signal list, details link).
  Acknowledge from the dashboard verified.
- Flagged-scan PDF export (7 pages) rendered and visually reviewed
  page-by-page: dark cover, executive summary, side-by-side
  baseline/current screenshots, timeline SVG, per-layer findings
  tables, numbered footer. Markdown export verified. Both filenames
  carry the site slug + scan-id prefix.
- Explain endpoint with no provider configured returns the clean
  "no AI provider is configured" degradation (503), not a stack trace.
- Telegram bot lifecycle against the live DB: idle with no token; a
  placeholder token saved through Settings was picked up from the DB
  within ~30s; Telegram's InvalidToken answered with the plain-language
  warning + 60s backoff (no crash-loop); token cleared, bot idle again.
  (`TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY` confirmed empty in .env —
  checked lengths only, values never printed.)
- Settings/Alerts/scan-drilldown UI driven headlessly against the live
  stack; screenshots reviewed against DESIGN-resend.md (true-black
  canvas, hairline cards, correct type lanes; no emoji).
- All QA fixtures cleaned up afterwards: verify site + channel deleted,
  local receivers stopped, scratch directories removed.

### Incidents & resolutions (found during this phase's QA pass)

1. **The SMTP test button did not actually gate Save.** §8 says "Send
   Test Email" gates the Save action, but the first implementation
   tested only stored settings — the user had to save unverified
   credentials first. Fixed: the test endpoint accepts inline unsaved
   settings (omitted password falls back to stored), and the frontend
   disables Save until a test passes against the current form values,
   re-locking on any edit. Two regression tests pin the endpoint
   semantics.
2. **Escalation integration tests initially asserted the wrong band** —
   the defacement fixture fuses to risk ~0.9999, above the tests' 0.9
   threshold, so the scan was already flagged and escalation never ran.
   Thresholds raised to 1.0 in those tests so the ambiguous-band path
   is genuinely exercised.
3. **`app/reporting.py`'s docstring contradicted the implementation**
   (claimed PDF rendering happens in the worker; it happens in the API
   process per the reports-router rationale). Docstring corrected —
   caught by the fresh-file re-read rule of the §13 charter.
4. **jsdom/Node Response mismatch in the new frontend test** — jsdom's
   Blob lacks `stream()`, so Node's `Response` constructor rejected it;
   fixed by passing bytes/strings directly, with an explanatory comment.
5. Access token expired twice during live verification (15-minute TTL,
   by design) — re-logged in from .env credentials without printing
   them. Same class as the Phase 3 incident; live-QA scripts now
   re-login as a matter of course.

### Deliberate deferrals (not bugs)

- **The LLM daily budget is per-process and in-memory** (resets on
  restart). It is a cost guardrail, not an entitlement system; a
  durable counter is unnecessary complexity at this scale.
- **The Telegram bot is single-owner by design** — one captured chat,
  every other chat refused. Multi-user bot access belongs with the
  Phase 5 RBAC work, if it is wanted at all.
- **Alert channels and settings are not RBAC-scoped yet** — the same
  standing deferral as every other mutating endpoint until the Phase 5
  role-enforcement pass.
- **Escalation runs only in the [0.35, 0.75) band on changed scans.**
  Below it the engine is confidently clean; above it the deterministic
  layers already flag. Widening the band is a tuning decision for
  real-world feedback, not a change to make now.
- **No live Gemini/Ollama key verification this phase** — no real keys
  exist in this environment; the invalid-key, rate-limit, and
  dead-endpoint degradation paths are covered by tests, and the
  Settings test buttons give the user a one-click live check once keys
  are added.
- **Manual negative/malformed-traffic QA** against the running stack
  remains the user's sign-off step outside Claude Code, per the
  Phase 0 sign-off decision — unchanged for this phase.

---

## Phase 5 — Advanced Features & Hardening (2026-07-17)

**Tests: 379 backend (was 313) + 25 frontend (was 19).** All green;
ruff, tsc, oxlint clean; pip-audit and pnpm audit report zero findings
(the Phase 0 "moderate, dev-only" pnpm deferral is now closed — nothing
at any severity). Live compose verification: 22/22 checks.

### What shipped

1. **RBAC on every endpoint.** `require_roles` dependency factory in
   `app/deps.py`; viewers read-only, analysts run monitoring and incident
   response (sites, scans, suppression, acks, explains, bulk import,
   remediation confirm/dismiss), admins everything (users, settings,
   channels, hooks, audit). The frontend hides what a role cannot do,
   but enforcement is entirely server-side. User management UI in
   Settings (create, role change, deactivate) with lockout guards: no
   self-demotion/self-deactivation, last-active-admin protected, and any
   role/password/deactivation change revokes the user's refresh-token
   families server-side.
2. **Audit log.** `app/audit.py` stages an `AuditLog` row on the caller's
   session so the audit commits atomically with the change it records.
   Covered actions: site create/update/delete/mute/rebaseline,
   suppression rules, settings (SMTP/Telegram/Gemini/Ollama), channels,
   alert acks (dashboard and Telegram-bot, the latter attributed
   "telegram-bot"), user management, API keys, remediation hooks and
   confirm/dismiss decisions, bulk imports. Key-fragment redaction
   (`password`, `token`, `secret`, `webhook_url`, `config`, ...) keeps
   secret values out at write time; site URLs deliberately stay. Admin
   UI at /audit with action-prefix, target-type, and actor filters.
3. **API keys.** `wk_`-prefixed, SHA-256 at rest, raw value shown
   exactly once at creation, revocable, honored by the same RBAC as the
   owner. Keys cannot manage keys (credential changes require a real
   session). `last_used_at` tracked (throttled to one write/minute).
   Bearer routing in `app/deps.py` inspects the prefix, so JWTs and API
   keys share one header.
4. **Bulk import.** `/api/sites/bulk-import`: CSV text (`url` or
   `url,name`) or sitemap crawl (urlset + one level of sitemapindex,
   lxml `no_network` + `recover`), 500-row/512 KB caps, per-row results
   (created/skipped/error, never all-or-nothing), per-row SSRF checks,
   baselines enqueued only after commit. Sites-page dialog with per-row
   result list.
5. **Remediation webhooks.** Per-site hooks (git_rollback,
   docker_restart, maintenance_page_swap, custom_webhook as payload
   labels), URL Fernet-encrypted and only ever surfaced as a redacted
   hint. `requires_manual_confirm=true` by default — flagged scans park
   executions in a confirm queue (/remediation) and nothing fires
   without an analyst decision; auto-execute is an explicit, warning-
   labeled per-hook opt-in. Firing happens in a separate Celery task
   (`worker/remediation_tasks.py`); a broken hook, dead endpoint, or
   full queue can never affect a scan (rule 6). Unique (hook, scan)
   index makes creation idempotent; a failed enqueue reverts the row to
   pending_confirm instead of stranding it.
6. **Security hardening.**
   - **DNS rebinding closed for raw-httpx fetches**: new
     `SSRFPinningTransport` (`app/ssrf_transport.py`) resolves,
     validates, and connects to the SAME address on every hop
     (redirects included), preserving Host + TLS SNI via httpcore's
     `sni_hostname` extension — no second resolution to race. Used by
     the probe layer and the sitemap crawler. Playwright still resolves
     independently; its guard remains post-redirect final-URL
     re-validation (documented in `app/ssrf.py`).
   - **Rate limiting**: fixed-window per-IP (pre-auth middleware) and
     per-user (post-auth dependency) limits, 429 + Retry-After,
     configurable via env, X-Forwarded-For honored only behind
     `TRUST_PROXY_HEADERS=true`.
   - **CORS**: locked to same-origin by default (empty allow-list; the
     SPA is served by the API container), env-configurable.
   - **Secrets audit**: no hardcoded credentials, no secret values in
     logs or audit rows, .env gitignored.
7. **Health/status.** `/api/health/live` (unauthenticated, no DB — now
   the compose healthcheck), `/api/health` readiness, and an authed
   `/api/health/details` powering the /health dashboard page: queue
   depth (Redis llen), worker liveness (broker-only Celery control ping
   — the API still never imports worker code), Beat liveness via a
   Redis heartbeat written by the dispatch tick, DB size
   (`pg_database_size`), scan latency and 24h counts, uptime. Probes
   run in threads with 2 s timeouts and every failure degrades to a
   labeled component status instead of an error page.

### Decisions

- **Settings/channels are admin-scope** (not analyst): they carry
  credentials and instance-wide delivery behavior. Analyst scope is
  operational monitoring; the split follows the kickoff's role list.
- **Audit rows are staged, not separately committed** — atomic with the
  change, and `record_audit` never raises (a broken audit path must not
  block the action it describes).
- **The dispatch heartbeat doubles as Beat + worker proof** (the tick is
  scheduled by Beat and executed by a worker), replacing the earlier
  next_scan_at heuristic.
- **API-key display prefix (`wk_` + 8 chars) is public by design** — it
  identifies keys in lists and audit rows; only the SHA-256 of the full
  key is stored.

### Incidents & fixes during the phase

1. **Confirm-queue stuck state**: a row confirmed while the queue was
   down would have stayed `queued` forever. Fixed: failed enqueue
   reverts to `pending_confirm` with a detail note, and stale `queued`
   rows accept re-confirmation.
2. **Enum-vs-string comparisons in the users router** (`User.role ==
   "admin"` never matches a StrEnum column under SQLAlchemy) — caught
   in review, converted to `UserRole` comparisons before any test ran.
3. **Beat container kept running the old image** after the worker-image
   rebuild — `docker compose up -d` does not recreate a running
   container whose config didn't change; explicit `--force-recreate`
   for beat is now part of the deploy notes.
4. **Live-check false positive**: the "no secrets in audit rows"
   heuristic flagged the public key display prefix; verified by
   inspection that only `key_prefix` is stored, never the raw key.

### Deliberate deferrals (not bugs)

- **Playwright DNS pinning** stays open as documented: browser
  navigation resolves DNS itself; the guard there remains post-redirect
  final-URL re-validation. Full pinning would require a proxy layer —
  out of proportion for Phase 5.
- **Rate-limit state is per-process memory** (fine at single-API-
  container scale; move to Redis only if the API is ever replicated).
- **Telegram bot liveness heartbeat** not surfaced on the health page
  (bot is optional and single-owner; worker/Beat/DB/Redis cover the
  scan-critical path).
- **Artifact-file janitor for deleted sites** still deferred from
  Phase 1 (rows cascade; files are small and harmless).
### Manual sign-off (completed 2026-07-17)

The user ran the manual negative/malformed-input pass against the live
stack (PowerShell, outside Claude Code): garbage JSON, missing fields,
bad URL schemes, loopback targets, fake JWTs, fake API keys, malformed
IDs, 40x wrong-password attempts, and an oversized bulk import. Every
probe returned a clean 4xx; no 500s, no crashes, all containers healthy
afterward. Two expectation notes (both correct behavior, wrong
prediction in the checklist):

- Loopback site targets reject with **422** (not 400) — the sites
  router surfaces SSRF violations as unprocessable input.
- An over-cap bulk import returns **200 with the first 500 rows
  processed and per-row results** — truncate-at-cap is the designed
  behavior (imports are never all-or-nothing), not a rejection. The
  one site this created was deleted afterward.

Phase 5 is signed off.

---

## Phase 6 Kickoff Prompt

Paste this into a fresh Claude Code chat, in the WARDRESS repo root:

---

**Wardress — Phase 6 Kickoff: Installer, Docs, Polish (final phase)**

Before writing any code, read these three files in full, in this order:
1. `WARDRESS_MASTER_PROMPT.md` — the complete project specification.
   §14 defines this phase; §13 (QA charter) and §15 (Definition of
   Done) bind every phase.
2. `DESIGN-resend.md` — the visual language. Nothing ships in default
   shadcn/Tailwind styling.
3. `PROGRESS.md` — everything already built through Phase 5, including
   decisions and deliberate deferrals. Do not re-litigate closed
   decisions; do honor the deferrals list when in scope.

**Current state (verified end of Phase 5):** 379 backend + 25 frontend
tests green; ruff/tsc/oxlint clean; pip-audit and pnpm audit zero
findings; live compose stack verified 22/22 (RBAC, audit log, API keys,
bulk import, remediation queue, rate limiting, health page); the user's
manual negative-input sign-off is complete (all clean 4xx, no 500s).
Alembic head: `f3c8d6a91b27`. Compose healthcheck now uses
`/api/health/live`. Note: after rebuilding the worker image,
`docker compose up -d --force-recreate beat` is required — a running
beat container is not recreated automatically.

**Phase 6 scope (§14 — the last phase):**

1. **`scripts/install.ps1` finished and tested** — one-command install
   on a clean Windows machine with Docker Desktop: generate `.env`
   secrets from `.env.example` (every CHANGE_ME replaced with a
   cryptographically random value), build images serially, run
   migrations, seed the admin user, print the dashboard URL and admin
   credentials exactly once. Idempotent re-runs must not clobber an
   existing `.env`.
2. **`scripts/update.ps1`** — pull/rebuild, migrate, restart (including
   the beat force-recreate gotcha), preserving data and `.env`.
3. **README.md** — the logo from `assets/`, screenshots of the real UI
   (ask the user to capture them if you cannot), feature overview,
   requirements, install/update/uninstall instructions, .env reference
   (including the Phase 5 rate-limit/CORS settings), role model table,
   API-key usage example, and the standing security notes (SSRF
   policy, secrets-at-rest, fail-safe alerting).
4. **Final full-system §13 QA pass** — every phase's functionality
   together, not in isolation: cross-feature flows (e.g. bulk-imported
   site → auto scan → flagged → alert + remediation confirm → audit
   trail; RBAC across every surface incl. artifacts/reports; restart
   resilience). Fix what you find, grow the suites.
5. **Polish** — anything the QA pass surfaces in UI consistency
   (design tokens, empty states, loading states) and OpenAPI
   completeness. Check the deferrals list in PROGRESS.md; close any
   that are cheap now (e.g. artifact-file janitor) or re-log them with
   reasons as permanent.

**Standing constraints (unchanged, binding):**
- All QA and testing work — including how it is reasoned about and
  described out loud — uses neutral engineering language: tests, edge
  cases, failure modes, validation, invariants, regression coverage.
  Do not frame or narrate QA as attacks, adversaries, or exploitation.
- The §13 QA pass runs directly in the main session — never delegated
  to a themed subagent persona.
- Negative/malformed-input probing of the RUNNING system is not
  performed by Claude Code — it is a manual user step in the sign-off
  checklist, executed outside Claude Code. Claude Code still writes
  unit/integration tests for malformed-input handling in application
  code.
- Never assume a library API — check `docs-cache/` or fetch docs
  first. Never add a package version you have not verified.
- uv and pnpm only (never pip/npm/yarn). No GPU deps. Secrets via
  `.env` only — never printed, never committed.
- New features fail safe: a broken hook, revoked key, or dead endpoint
  must never break scanning.
- No emoji anywhere in the product. Follow DESIGN-resend.md tokens.
- Build Docker images serially in the foreground — never overlap
  builds in background tasks.
- Update `PROGRESS.md` at the end. This is the final phase: close it
  with a "Project complete" summary instead of a Phase 7 prompt, plus
  a maintenance checklist (how to update deps, re-run audits, rotate
  secrets).
- Remind the user of their manual negative-input QA sign-off step at
  the end.

---

## Phase 6 — Installer, Docs, Polish (2026-07-18, FINAL)

**Shipped.** One-command installer, updater, README with real-UI
screenshots, the full-system §13 QA pass, and the last polish items.
Backend 383 tests, frontend 25 tests, tsc clean, ruff clean, oxlint at
the 2 accepted fast-refresh warnings.

### scripts/install.ps1 (tested three ways)

Flow: Docker checks (actionable errors + docker.com link) -> `.env`
generation from `.env.example` on first run only (every CHANGE_ME
assignment replaced with a crypto-random value; the DB password is kept
identical in `POSTGRES_PASSWORD` and inside `DATABASE_URL`; existing
`.env` never touched, and a leftover CHANGE_ME in an existing `.env`
fails loudly) -> serial foreground image builds (app, worker, beat) ->
db/redis up -> `alembic upgrade head` -> stack up -> health poll ->
idempotent admin seed -> Desktop shortcut (`Wardress.lnk`, brand icon,
non-fatal on failure) -> summary that prints the generated admin
credentials exactly once on first install and never again.

Verified by: (1) isolated `.env`-generation harness (password sync,
distinct 43-char secrets, LF endings, byte-identical on re-run); (2) a
full clean-machine simulation under a renamed compose project on port
8322 — fresh install, login with the printed credentials, update run,
data survival, `down -v` teardown; (3) idempotent re-run against the
real stack (`.env` untouched, no credentials printed, admin seed
"already exists").

PowerShell 5.1 portability rules learned and encoded: keep the scripts
pure ASCII (BOM-less UTF-8 is read as ANSI by 5.1 and em-dash bytes
break string parsing); `RandomNumberGenerator::Fill()` does not exist
on .NET Framework (use `Create()`/`GetBytes()` + rejection sampling);
under `$ErrorActionPreference = "Stop"` redirected native stderr
becomes a terminating error (probe commands via an Invoke-Quiet
helper).

### scripts/update.ps1

`git pull --ff-only` (skippable with `-NoGitPull`, only when a git repo
with an origin exists) -> prints CHANGELOG.md head if present -> pull
db/redis, rebuild app/worker/beat serially -> migrate -> restart app +
worker -> **always** `up -d --no-build --force-recreate beat` (the
standing gotcha: compose will not recreate a running beat whose own
config did not change after a worker-image rebuild) -> telegram-bot
force-recreate only if it is running -> health poll. Data, artifacts,
and `.env` preserved (verified live in the clean-machine simulation).

### Final §13 QA pass (main session, neutral engineering framing)

**Cross-feature incident flow — 26/26 checks green** against the live
stack with a local demo page and a local webhook receiver: CSV bulk
import -> automatic baselines; demo site baseline; Apprise channel +
manual-confirm remediation hook; page content swap -> flagged scan at
risk 1.0; alert row with delivery `sent` and the webhook actually
received; execution `pending_confirm` -> confirm -> `succeeded` with
the remediation webhook received; audit trail rows for site/channel/
hook/remediation with no webhook URL leaked; PDF (`%PDF` magic) and
Markdown exports; ack; page restored.

**RBAC matrix over every surface class** (throwaway analyst/viewer
accounts, deactivated afterwards): viewer read-everywhere (incl.
artifact screenshots and report exports) and denied on every mutation;
analyst operational (sites, scan-now, suppression, threshold PATCH)
and denied on admin surfaces (users, settings, channels, hooks,
audit); anonymous artifact access 401. API keys: created once with
`wk_` raw value shown once, key auth works at owner role, keys cannot
manage keys, revoked key rejected immediately.

**Restart resilience**: full `docker compose restart` -> all services
healthy, data intact, health details all ok, post-restart scan clean,
Beat ticking and dispatching due scans (adaptive cadence picked a due
site up on the first tick after restart).

**Failure mode**: baseline against a genuinely closed port fails
cleanly to `baseline_status=failed` with a user-safe fetch error.

**Findings fixed this pass:**

1. **Settings reads were not admin-scoped** — `GET /api/settings/*`
   and `GET /api/notification-channels` used `CurrentUser` while every
   mutation was admin-only. The Phase 5 decision ("settings/channels
   are admin-scope") now holds end to end: all five reads are
   `AdminUser`, with a regression test sweeping them for analyst and
   viewer. No frontend change needed — only admin-gated cards consumed
   them.
2. **Phase 5 env knobs never reached the container** — `RATE_LIMIT_*`,
   `TRUST_PROXY_HEADERS`, `CORS_ALLOWED_ORIGINS` were documented in
   `.env.example` but absent from the compose `environment:` block, so
   edits silently did nothing (defaults happened to match). Now passed
   through on the app service, along with the new `COOKIE_SECURE`.
3. **11 Phase 5 files had drifted from ruff format** — reformatted, no
   behavior change.

**Non-findings worth recording:** analyst API-key creation is by
design (self-service keys at the owner's role, pinned by
`test_api_key_authenticates_with_owner_role`); an initial
"unreachable-target" failure was a fixture collision with a live
listener on the chosen port, not a product issue.

### Polish and deferral disposition

- **Artifact-file janitor (Phase 1 deferral) — CLOSED.** Daily Beat
  task `wardress.cleanup_orphan_artifacts`: removes only well-formed
  UUID directories under `baselines/` and `scans/` whose owning row is
  gone; per-run removal cap; never touches anything else on the
  volume; best-effort by contract (an error can never affect
  scanning). Three unit tests; live run removed 23 orphan directories
  from earlier phases and kept all live ones.
- **`cookie_secure` / HTTPS fronting (Phase 1 deferral) — CLOSED.**
  `COOKIE_SECURE` added to `.env.example` (with the reverse-proxy
  guidance) and compose; README documents the HTTPS fronting recipe
  (PUBLIC_BASE_URL + TRUST_PROXY_HEADERS + COOKIE_SECURE).
- **OpenAPI completeness — verified**: 62 routes, every one tagged and
  described.
- **README.md** — logo, eight real-UI screenshots (`docs/screenshots/`,
  captured from the live dashboard populated by the QA flow), feature
  overview, nine-layer table, requirements, install/update/uninstall,
  full `.env` reference, role table, API-key example, security notes
  (SSRF policy, secrets at rest, fail-safe alerting, rate limiting).

**Permanent deferrals (by design, with reasons):**

- LLM daily budget is per-process/in-memory — a cost guardrail, not an
  entitlement system.
- Telegram bot is single-owner — one captured chat by design.
- LLM escalation band stays [0.35, 0.75) on changed scans — tuning
  belongs to real-world feedback.
- The 2 oxlint fast-refresh warnings — upstream shadcn file layout.
- No live Gemini/Ollama key verification — no real keys in this
  environment; Settings test buttons cover it the moment keys exist.

---

## Project complete

Wardress is finished per the master prompt: a self-hosted,
Docker-Compose-deployed defacement monitor with a nine-layer detection
engine and fused risk scoring, adaptive Beat scheduling, a SOC-style
React dashboard (drilldowns, visual/DOM diffs, suppression), alerting
across SMTP/Telegram/Apprise with per-delivery tracking, guarded
manual-confirm remediation hooks, optional Gemini/Ollama incident
explanations, bulk import, server-side RBAC (admin/analyst/viewer),
per-user API keys, an audited configuration surface with secrets
encrypted at rest, PDF/Markdown reports, a health page, a one-command
Windows installer/updater, and a documented README. Final state:
383 backend + 25 frontend tests green; ruff/tsc clean; OpenAPI fully
documented; all deferrals closed or logged permanent with reasons.

### Maintenance checklist

- **Update dependencies** (occasionally, deliberately):
  `cd backend && uv lock --upgrade && uv sync && uv run pytest`;
  `cd frontend && pnpm update --latest && pnpm test && pnpm exec tsc
  --noEmit`. Rebuild images afterwards via `scripts/update.ps1`. Never
  add a package version without checking its changelog.
- **Re-run audits**: `uv run pip-audit` (backend) and `pnpm audit`
  (frontend) after every dependency refresh; re-run the full suites
  and a live scan-flag-alert smoke check after any upgrade.
- **Rotate secrets**: generate a new value into `.env` and restart the
  stack. `JWT_SECRET` rotation signs everyone out (harmless).
  `POSTGRES_PASSWORD` must be changed in Postgres itself (`ALTER
  USER`) and in both `.env` lines (`POSTGRES_PASSWORD`, inside
  `DATABASE_URL`) together. `CREDENTIALS_ENCRYPTION_KEY` cannot be
  swapped blindly — stored channel/SMTP credentials are encrypted with
  it; re-enter those credentials in Settings after rotating. Admin
  password changes happen in the UI (`ADMIN_PASSWORD` in `.env` is
  only the first-boot seed).
- **Data hygiene**: Postgres lives in the `db-data` volume — back it
  up with `docker compose exec db pg_dump -U wardress wardress`. The
  artifact janitor prunes orphaned baseline/scan files daily; alert
  and audit rows are kept indefinitely by design.
- **Standing sign-off step (manual, outside Claude Code)**:
  negative/malformed-input probing of the running system — malformed
  request bodies, oversized payloads, boundary values on the API, and
  hostile page content on scan targets — remains the user's manual QA
  step before each release-grade milestone.

---

## Post-completion: live key configuration + Gemini model fix (2026-07-18)

First real API keys added by the user (`GEMINI_API_KEY` and
`TELEGRAM_BOT_TOKEN` in `.env`, values never printed or committed) and
live-verified through the product's own Settings test endpoints. Both
keys were also seeded into the dashboard Settings store (encrypted at
rest, the source of truth; `.env` remains only the bootstrap default).

**Bug found and fixed by the live test (`727e877`):** Google retired
`gemini-2.5-flash` — the model the master prompt pinned "everywhere" —
for newly created API keys; `generateContent` returns 404 NOT_FOUND
while ListModels still advertises the name. Diagnosis was done against
the API itself from inside the app container (ListModels + a live
`generateContent` probe, key read from the environment only). Default
switched to `gemini-flash-latest`, Google's stable alias for the
current flash model, so the default cannot rot when a pinned version is
retired again. Changed in `app/llm.py` (constant + docstrings),
`app/config.py`, `app/schemas.py`, `app/routers/settings.py` docstring,
`docker-compose.yml` fallbacks, `.env.example`, the user's `.env`, and
the `test_gemini_settings_flow` pin. App/worker/beat images rebuilt
serially, beat force-recreated per the standing gotcha. 383 tests pass.

**Verified end state:** `POST /api/settings/gemini/test` -> "Key works
— gemini-flash-latest answered"; `POST /api/settings/telegram/test` ->
"Test message sent" (the bot container is polling, the owner chat was
captured via /start, and the test message arrived in Telegram). Alert
delivery to Telegram and LLM incident explanations/escalation are now
active on this install.

**Maintenance note for future model retirements:** if Gemini calls
start failing with 404 again, list the models available to the key
(`GET /v1beta/models` with the `x-goog-api-key` header) and update
`GEMINI_MODEL` in `.env` — the code default already tracks the alias,
so this should only matter if Google retires the alias scheme itself.

---

## Post-audit: Critical fixes + needs-user-decision dispositions (2026-07-18)

Worked the audit report's blocking tiers: the 2 CRITICALs and the 8
`needs-user-decision` items. Every decision now has a recorded outcome
in `WARDRESS_AUDIT_REPORT.md`; both Criticals are resolved (one fixed,
one shown to be a false positive by build inspection).

**CRITICAL #1 — bulk import per-row DB error rolled back the whole
import (fixed).** `app/routers/imports.py`: a CSV-supplied `name` was
inserted unbounded into `Site.name` (VARCHAR 200); on Postgres an
over-length value raised `DataError` at flush and, with a single shared
session and no per-row guard, took down every previously-flushed row in
the same import — the all-or-nothing failure §11 forbids. Fix: cap the
name to `SITE_NAME_MAX=200` before insert, and wrap each row's
create/flush in `db.begin_nested()` (SAVEPOINT) with `except
SQLAlchemyError`, so a bad row becomes `status="error"` (generic detail,
no DB internals leaked) and the rest of the import commits. Verified
three ways: 3 new tests in `test_phase5_bulk_import.py` (name truncated
not errored; a forced `IntegrityError` row isolated while sibling rows
persist; DB count assertions), the SQLite suite green — **and live on
the compose Postgres**, because SQLite does not enforce VARCHAR lengths
and structurally cannot catch this. Live proof: a 500-char name in a
mixed 3-row batch created all 3 sites with the name truncated to 200 and
0 errors; app image rebuilt serially, container recreated healthy, the 4
test sites deleted afterward.

**CRITICAL #2 — "Recharts not code-split" (deferred: not a defect).**
The finding claimed static imports inside the `lazy()`-loaded chart
components get bundled into the main chunk at parse time. Built the
frontend and inspected the emitted chunks instead of trusting the
premise: the main chunk (`index-*.js`) has zero Recharts references and
zero static/dynamic imports of the chart chunk; Recharts core sits in
its own async chunk (`CategoricalChart-*.js`, 254 kB) reached only via
the two page-level `lazy()` chunks (`risk-gauge`, `incident-timeline`).
The chart chunk's only mention in the main bundle is inside Vite's
`__vitePreload` dep map, fetched when the dynamic import fires, not on
initial load. Already code-split as Phase 3 required; no code change.

**Decision 8-real — `allow_private_networks` on a sitemap crawl is now
admin-only (implemented alongside the Criticals).** That flag relaxes
SSRF for the crawl fetch plus every child-sitemap fetch and redirect
hop, turning the server into an internal-network fetcher whose `<loc>`
text is echoed back. `bulk_import` now returns 403 when a non-admin sets
the flag with `sitemap_url`; CSV imports (which never crawl) keep the
flag for analysts, where it only governs the per-row SSRF check. Schema
`description` updated to state the restriction. 3 new tests (analyst
sitemap+flag → 403 with the crawl proven not to run; admin sitemap+flag
→ 200; analyst CSV+flag → 200).

**The other 7 decisions were recorded, not yet implemented** (direction
settled, implementation scoped to later tiers per the user): site-
visibility scoping (dedicated follow-up — large), API-key creation
restricted to analyst+admin (Low tier), audit-coverage expansion (Low),
SMTP test-success token gating the PUT (Low), Telegram unauthorized-chat
silent-drop + log (Medium), WeasyPrint libs dropped from Dockerfile.
worker (Low/infra), and the body-md/button-sm font lane ratified to
Instrument Sans — the one doc-only decision, applied this session in
`WARDRESS_MASTER_PROMPT.md` §4. The out-of-scope remediation-hook Medium
also has a pre-decided direction (gate to AdminUser).

**Verified end state:** backend 388 passed (was 383; +5 new), frontend
25 passed, `tsc --noEmit` clean, oxlint only pre-existing fast-refresh
warnings (no frontend files changed this session), ruff clean/formatted.
