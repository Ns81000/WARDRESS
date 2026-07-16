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
