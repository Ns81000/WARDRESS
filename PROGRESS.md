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

