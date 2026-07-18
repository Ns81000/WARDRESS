# WARDRESS — Master Build Prompt for Claude Code (Opus 4.8)

> **How to use this file:** Keep this file (`WARDRESS_MASTER_PROMPT.md`) and `DESIGN-resend.md` (design tokens, adapted below) in the project workspace root at all times. At the start of every new chat/phase, paste the "Phase N Kickoff Prompt" that the previous phase generated (see §14). This master file never changes; `PROGRESS.md` (created in Phase 0) is the living memory that accumulates across phases. Read this entire file before writing any code, in any phase.

---

## 0. Mission Statement

Build **Wardress** — a free, self-hosted, open-source website defacement detection and monitoring platform. A user adds a URL, the system captures a trusted baseline (HTML, DOM, screenshot, headers, TLS cert), then periodically re-checks the site through nine parallel detection layers, computes a fused risk score, and alerts the user through whichever channels they've configured (Email/SMTP, Telegram, ntfy, Discord, Slack, or any Apprise-supported service). It ships as a Docker Compose stack for Windows, installed and updated with single scripts, with a beautiful, hand-designed React dashboard — never default component styling, never AI-slop visual clichés (no purple-neon gradients, no emoji-as-icons, no generic dashboard templates).

This is a **production-grade** deliverable: clean, fully documented, thoroughly tested code, with zero known bugs at the end of each phase before moving to the next. Every phase ends with a full main-session QA pass (§13) before being marked complete.

### Absolute rules for every phase
1. **Never assume.** If unsure how a library's API works, fetch the real documentation (§2 lists exact URLs and llms.txt equivalents) before writing code that uses it.
2. **Never use a package version you haven't verified is current and compatible.** Pinned versions are given in §1 — treat them as the source of truth, but if a listed version fails to install, re-check the package's actual release page before downgrading, and log why in `PROGRESS.md`.
3. **No heavy-GPU dependencies, anywhere, ever.** Every detection layer, every ML component, every embedding model must run acceptably on a CPU-only Windows machine.
4. **No commercial/paid fonts, images, or assets** may be vendored into the repository. Only OFL/Google-Fonts/Apache/MIT-licensed assets.
5. **`uv` for all Python dependency management. `pnpm` for all Node/frontend dependency management.** Never `pip install` directly, never `npm`/`yarn`.
6. **Every feature that touches the user's data, secrets, or remote infrastructure must fail safely** — a broken notification, a Gemini quota error, an unreachable target site must never crash a scan or corrupt state.
7. **Update `PROGRESS.md`** at the end of every phase (§14) before producing the next phase's kickoff prompt.

---

## 1. Technology Stack (pinned, verified current as of this prompt's writing)

### Backend
| Component | Choice | Version / notes |
|---|---|---|
| Language | Python | 3.12 |
| Package manager | **uv** (Astral) | latest; use `uv sync --frozen` with committed `uv.lock`; Docker layer-cached per Astral's official pattern (copy `uv` binary from `ghcr.io/astral-sh/uv:<pinned-tag>`, install deps layer before copying source) |
| Web framework | FastAPI | latest stable; async throughout |
| ORM | SQLAlchemy 2.x (async) + Alembic | migrations mandatory from commit 1 |
| Task queue | Celery + Redis | Celery Beat for the recurring scan scheduler |
| Browser automation | Playwright (Python) | pin to `1.61.0`; use the official `mcr.microsoft.com/playwright/python` Docker base image for the worker container |
| DOM parsing/diff | `lxml` | |
| Visual diff | `scikit-image` (SSIM) + `imagehash` (pHash/dHash) | |
| Semantic/fusion layer | `sentence-transformers` with `all-MiniLM-L6-v2` (CPU) + `scikit-learn` (logistic regression / gradient boosting) | no GPU, no CNN |
| Optional cloud LLM | Google Gemini via the **`google-genai`** SDK | model string is exactly **`gemini-2.5-flash`** — use this literal string everywhere in code, config, and docs. User supplies their own free API key from Google AI Studio. |
| Optional local LLM | Ollama (OpenAI-compatible endpoint) | fully offline alternative to Gemini, user's choice |
| Notifications | **Apprise** | handles Email, Discord, Slack, ntfy, and 100+ others via URL strings |
| Telegram (interactive) | **python-telegram-bot** (v22.x, async) | separate from Apprise's push-only Telegram support — this is a real two-way bot |
| Email templating | Jinja2 + `premailer` (CSS inlining) | sent via `aiosmtplib` |
| PDF reports | **WeasyPrint** (Jinja2 → HTML/CSS → PDF) | not Playwright — see rationale in `PROGRESS.md` seed notes (§14); needs Pango/Cairo/GDK-PixBuf system libs in the Dockerfile |
| Rate limiting (Gemini) | `aiolimiter` (token bucket) | tuned conservatively under the free-tier ceiling; exponential backoff on HTTP 429 |
| Auth | JWT (short-lived) + refresh rotation, Argon2id password hashing | |
| Database | PostgreSQL 16 | |
| Cache/broker | Redis | |

### Frontend
| Component | Choice | Version / notes |
|---|---|---|
| Framework | React 19 | |
| Build tool | Vite | with `@vitejs/plugin-react` and `@tailwindcss/vite` |
| Package manager | **pnpm** | always |
| CSS | Tailwind CSS v4 | |
| Component layer | shadcn/ui, "new-york" style | install via CLI, then **heavily reskin every component** against the design tokens in §4 — never ship an unstyled default shadcn look |
| Charts | Recharts | dark-mode tuned per design tokens |
| DOM tree viewer | custom renderer (do not use `react-json-view`'s default theme — restyle fully) |
| State/data fetching | TanStack Query | |
| Routing | React Router v7 | |
| Icons | `lucide-react` | monochrome, sized precisely, never default stroke-width without checking against the design system |

### Infrastructure
| Component | Choice |
|---|---|
| Containerization | Docker Compose, single host, **Docker Desktop already installed on the target Windows machine** (do not write auto-install logic for Docker itself — assume present, but the installer script must verify it's running and give a clear error message with a link if not) |
| Services | `app` (FastAPI), `worker` (Celery), `beat` (Celery Beat), `db` (Postgres), `redis`, `frontend` (built static, served via the `app` container or a small nginx container — decide in Phase 1 and document the choice in `PROGRESS.md`), `telegram-bot` (small dedicated container or a thread inside `worker` — decide and document) |
| Optional service | `ollama`, only started if the user enables local-LLM mode via an env flag |

---

## 2. Documentation Claude Code must actually read (not recall from memory)

Before implementing any integration below, fetch and read the real current docs. If a tool exposes an `llms.txt` or llms-friendly docs page, prefer it.

- Playwright Python: https://playwright.dev/python/docs/intro (release notes: https://playwright.dev/python/docs/release-notes)
- FastAPI: https://fastapi.tiangolo.com/
- SQLAlchemy 2.0 async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Alembic: https://alembic.sqlalchemy.org/
- Celery: https://docs.celeryq.dev/
- shadcn/ui (Vite + Tailwind v4 + React 19): https://ui.shadcn.com/docs/installation/vite and https://ui.shadcn.com/docs/tailwind-v4
- Tailwind CSS v4: https://tailwindcss.com/docs/installation/using-vite
- Apprise (all notification URL formats, including `ntfy://` and `mailto://`): https://github.com/caronc/apprise/wiki
- python-telegram-bot: https://docs.python-telegram-bot.org/ (tutorial: their wiki "Introduction to the API" and "Your first bot")
- ntfy: https://docs.ntfy.sh/
- Google Gen AI SDK (Gemini): https://ai.google.dev/gemini-api/docs — **model id: `gemini-2.5-flash`**, rate-limit docs at https://ai.google.dev/gemini-api/docs/rate-limits
- WeasyPrint: https://doc.courtbouillon.org/weasyprint/stable/
- uv (Astral), Docker integration guide: https://docs.astral.sh/uv/guides/integration/docker/
- scikit-image SSIM: https://scikit-image.org/docs/stable/api/skimage.metrics.html
- imagehash: https://github.com/JohannesBuchner/imagehash
- sentence-transformers: https://www.sbert.net/
- changedetection.io (reference architecture only — study scheduling/notification/browser-steps patterns, do not fork or copy code): https://github.com/dgtlmoon/changedetection.io
- Anthropic docs (for Claude Code's own reference on tool use, if needed): https://docs.claude.com

When any implementation detail in this prompt conflicts with what the live documentation says (APIs change), **the live documentation wins** — note the discrepancy and the resolution in `PROGRESS.md`.

---

## 3. Product Identity

- **Name:** Wardress (working name — logo and README should treat this as final unless a licensing/trademark conflict is discovered, in which case fall back to "Sitewarden" and note the change in `PROGRESS.md`)
- **Logo:** an abstract geometric shield/ward mark, monochrome (white on the true-black canvas from §4), drawn as clean inline SVG by Claude Code itself — no external icon libraries for the primary mark. Must remain legible from 16px (favicon) to 512px (Windows shortcut icon / app tile). Provide the SVG source in `/assets/brand/wardress-logo.svg`, plus exported PNG/ICO sizes needed for a Windows shortcut icon (16, 32, 48, 256).
- **Tagline direction:** something short conveying vigilance over a website's integrity/authenticity — Claude Code should propose 3 options in Phase 1 and pick one, documenting the choice.

---

## 4. Design System (adapted from `DESIGN-resend.md`)

Use every token, spacing value, radius rule, and component spec in `DESIGN-resend.md` **verbatim**, with exactly these font substitutions (the originals are commercial fonts that cannot be redistributed in an open-source self-hosted repo):

| Token role | Original (do not use — paid) | Replacement (use this — free/OFL) |
|---|---|---|
| `display-xxl`, `display-xl` (hero/headline serif) | Domaine Display | **Fraunces** (variable font, Google Fonts, use the `opsz` axis at high values for the display cut, tight `line-height: 1.0` exactly as the original spec mandates) |
| `display-lg`, `subtitle`, `body-md`, `button-sm` (marketing body / ABC Favorit lane) | ABC Favorit | **Instrument Sans** for `display-lg`/`subtitle`/`body-md`/`button-sm` roles, **Inter** for the remaining UI roles (`heading-*`, `body-lg`, `body-sm`, `button-md`, `caption`) — keep the "strict lane" rule from the original doc: never mix these two outside their assigned roles |

> **Font-lane clarification (ratified 2026-07-18, audit Critical/decisions session).** The row above is the authoritative reading of the earlier draft table, which ambiguously said "Inter for `body-md`/UI roles." `body-md` and `button-sm` are **ABC Favorit** tokens in `DESIGN-resend.md`, so their substitute is **Instrument Sans**, not Inter — this is exactly what the "-0.5% tracking compensation on body sizes" rule two paragraphs below implies (that compensation only applies to the ABC Favorit substitute), what `frontend/src/index.css` implements (body-md tracking = −0.88px = −0.8 + −0.5% of 16px), and what PROGRESS.md Phase 1 documented ("Instrument Sans (display-lg/subtitle/body-md lane …)"). No code or visual change resulted from this ratification — it only resolves the spec's internal contradiction.
| `code-md` | Geist Mono | **unchanged** — Geist Mono is already SIL OFL licensed, free for commercial use, keep it exactly as specified |

Everything else in `DESIGN-resend.md` — the true-black `#000000` canvas, hairline borders instead of drop shadows, `rounded.lg` (12px) cards, the accent-glow tokens (orange/blue/green/red used as *low-opacity radial glows only, never solid fills*), the "one white surface per viewport" rule, the button/card/nav-bar component specs, the responsive breakpoint table — carries over exactly as written. Read the full `DESIGN-resend.md` file before building any UI component.

### Wardress-specific design additions (not in the original marketing-site doc, needed for a SOC dashboard)
- **Threat-state color mapping:** clean (`accent-green` glow), investigating/pending (`accent-orange` glow), confirmed defacement (`accent-red` glow, used sparingly and only on the specific flagged site card, never as a page-wide wash)
- **Visual diff slider component:** side-by-side baseline/current screenshot with a draggable divider; altered-pixel regions highlighted with a translucent `accent-red` overlay (never solid neon red fill)
- **DOM diff tree:** added nodes get a subtle `accent-green` left-border accent, removed nodes get `accent-red`, both at low opacity, on the standard `surface-card` background — no bright green/red text-on-black "hacker movie" styling
- **Status dot component:** reuse `{component.status-dot}` from the original doc exactly, remapped semantically to scan/site health
- Absolutely no emoji anywhere in the UI, code, or generated reports. No decorative icons that don't map to a real lucide-react semantic icon.

---

## 5. Detection Engine — Nine Layers

Each layer is a discrete, independently testable function that takes `(baseline, current_scan_data)` and returns `{score: float 0-1, evidence: dict}`. Cheaper layers gate more expensive ones (don't run layer 4 visual diff if layer 1 hash is already identical, for performance — but always log that the layer was skipped and why).

| # | Layer | Method | Library |
|---|---|---|---|
| 1 | Cryptographic hash | SHA-256 of normalized static content | stdlib `hashlib` |
| 2 | DOM structural diff | Tag-tree diff, `<script>`/`<iframe>`/hidden-element counting | `lxml` |
| 3 | Link/script audit | Diff `<script src>` and `<a href>` sets vs baseline | `lxml` |
| 4 | Visual diff | Full-page screenshot → SSIM + pHash/dHash | Playwright + `scikit-image` + `imagehash` |
| 5 | Signature/keyword match | Regex list of known defacer phrasing, profanity, script-mixing detection (sudden non-Latin text where baseline was Latin, etc.) | stdlib `re` |
| 6 | Security metadata | TLS cert expiry/thumbprint diff, security headers (CSP/HSTS/X-Frame-Options), robots.txt/sitemap diff | `httpx`, stdlib `ssl` |
| 7 | Cloaking/geo detection | Rotate User-Agent (Googlebot/mobile Safari/desktop Chrome); optional multi-region fetch if user configures proxy nodes | Playwright |
| 8 | NLP/semantic | Keyword+sentiment pass locally; optional Gemini (`gemini-2.5-flash`) or Ollama call for ambiguous cases only | `sentence-transformers`, `google-genai`, Ollama |
| 9 | Fusion classifier | Combines all above sub-scores + MiniLM text embedding into one calibrated risk score via a lightweight scikit-learn model (logistic regression to start; document upgrade path to gradient boosting once enough scan history exists per site) | `scikit-learn` |

Each layer's evidence (matched keywords, diff snippets, new-link lists, before/after header diffs) is stored in `scan_findings` for UI drilldown — never just a bare number.

### False-positive suppression
Users must be able to click a region on the live screenshot and mark it "ignore" (stored as a CSS-selector or bounding-box exclusion per site), and add regex exclusions for dynamic text. This has to be a real point-and-click UI feature, not just a config text field.

---

## 6. Database Schema (extend, don't shrink, the shape from `defacement-detector-spec.md`)

Base this on the schema already sketched (`sites`, `baselines`, `scans`, `scan_findings`, `alerts`, `users`), and add:

- `organizations`/RBAC: `role` enum (`admin`, `analyst`, `viewer`) on `users`, scoped to sites they can see
- `suppression_rules` (site_id, type: `css_selector`|`regex`|`bbox`, value, created_by, created_at)
- `audit_log` (actor_id, action, target_type, target_id, before_json, after_json, created_at) — every config change, baseline reset, and alert-channel edit must write here
- `notification_channels` (user_id, type: `email`|`telegram`|`apprise_url`, config JSON encrypted at rest, is_active)
- `api_keys` (user_id, key_hash, label, created_at, last_used_at, revoked_at)
- `remediation_hooks` (site_id, trigger_threshold, webhook_url, requires_manual_confirm boolean default true, action_type: `git_rollback`|`docker_restart`|`maintenance_page_swap`|`custom_webhook`)

Use Alembic migrations for every schema change from the very first commit — no hand-edited schema.

---

## 7. API Surface (FastAPI, fully OpenAPI-documented)

Extend the endpoint list already sketched in `defacement-detector-spec.md` (`/api/sites`, `/api/sites/{id}/rebaseline`, `/api/sites/{id}/scan-now`, `/api/sites/{id}/scans`, `/api/scans/{id}`, `/api/scans/{id}/diff`, `/api/alerts`, `/api/settings/notifications`) with:

- `/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout`
- `/api/users` (admin-only CRUD, RBAC-scoped)
- `/api/sites/{id}/suppression-rules` (CRUD)
- `/api/sites/bulk-import` (CSV upload)
- `/api/reports/{scan_id}/pdf` and `/api/reports/{scan_id}/markdown` (export)
- `/api/settings/telegram` (bot token + chat ID management, with a test-message endpoint)
- `/api/settings/gemini` (API key storage — encrypted — with a test-call endpoint that makes one cheap `gemini-2.5-flash` call to confirm the key works)
- `/api/settings/smtp` (with a send-test-email endpoint)
- `/api/health` (worker queue depth, last scan latency per site, DB size, uptime) — powers the operational status page
- `/api/audit-log` (paginated, filterable)

---

## 8. Notifications, Reports, and the Optional Intelligence Layer

### Email
Jinja2 HTML templates, CSS inlined with `premailer`, sent via `aiosmtplib` using the user's own SMTP credentials (Settings screen must show clear inline instructions, e.g. Gmail App Password guidance, with a working "Send Test Email" button gating the Save action).

### PDF & Markdown reports
WeasyPrint renders Jinja2-templated HTML/CSS to PDF (system deps: Pango, Cairo, GDK-PixBuf in the Dockerfile). Reports must include a cover page, executive summary, per-layer findings with embedded diff thumbnails, an incident timeline chart (pre-rendered as a static image, not live JS), and numbered pages with running headers/footers via CSS Paged Media. Test this on a multi-page report specifically — page-break behavior around tables and images is the most common "broken PDF" failure mode; verify visually before considering this done.

### Telegram bot (two-way, simple)
`python-telegram-bot`. Commands: `/status`, `/sites`, `/scan <name>`, `/ack <id>`, `/mute <site> <duration>`, `/help`. Setup flow surfaced in-app: message `@BotFather` → `/newbot` → paste token into Settings → send `/start` to the new bot once to auto-capture the chat ID. Keep this bot's scope intentionally small — it is not meant to replace the dashboard, only to give quick pull-based status checks and simple acknowledgements. Outbound alert pushes to Telegram go through Apprise's `tgram://` URL support, not through this bot.

### ntfy
No custom integration code required — it's natively supported as an Apprise notification URL (`ntfy://` / `ntfys://`). Surface it in the Notifications settings screen as a one-click-friendly recommended option (no account required, works with the free ntfy.sh or a self-hosted instance), alongside Discord/Slack/email/webhook.

### Gemini (`gemini-2.5-flash`) — optional cloud intelligence
- SDK: `google-genai` (`from google import genai`). **Always use the exact model string `gemini-2.5-flash`** in code, config defaults, and documentation.
- User provides their own free API key in Settings (with a "Get your free key" link to https://aistudio.google.com/apikey and one sentence explaining the free tier is generous but rate-limited).
- Used only for: (a) semantic classification of scans whose fused risk score lands in an ambiguous middle band, not every scan; (b) an "Explain this incident" button in the dashboard and Telegram bot that summarizes scan findings in plain English.
- Rate limiting: `aiolimiter` token bucket tuned conservatively (assume ~8 requests/minute, ~200/day, to stay safely under published free-tier ceilings which can shift), plus exponential backoff on HTTP 429.
- **Must degrade silently.** If the API key is missing, invalid, or quota-exhausted, log it, skip the semantic layer, and continue the scan pipeline normally. This feature must never be able to block or crash a scan.
- Local Ollama remains available as a fully-offline alternative for users who don't want any cloud API call at all; both are optional toggles, neither is required for the core product to function.

---

## 9. Security Requirements

- Argon2id for password hashing, JWT short-lived access tokens + rotating refresh tokens
- SSRF protection on every target-site fetch: deny-list RFC1918/loopback/link-local ranges by default, with an explicit opt-in per site if a user genuinely wants to monitor something on their internal network
- Secrets (DB password, JWT signing secret, encryption key for stored notification credentials) generated at install time into a `.env` that is gitignored and never has a hardcoded/guessable default
- Rate-limited API (per-user and per-IP), CORS locked to the app's own origin only
- Dependency audit step (`uv pip audit` equivalent / `pip-audit`, `pnpm audit`) run in Phase 0 and wired into CI
- Remediation webhooks (§6 `remediation_hooks`) default to `requires_manual_confirm = true` — auto-executing rollbacks must be an explicit, clearly-labeled opt-in, never a default, given the real risk of a false positive triggering an unwanted rollback

---

## 10. Installer & Updater (Windows, Docker Desktop already installed)

Build these as PowerShell scripts in `/scripts/`:

- **`install.ps1`**: verifies Docker Desktop is installed and the daemon is running (clear, actionable error message with a link to docker.com if not — do not attempt to silently install Docker itself); pulls/builds the Compose stack; generates the `.env` with cryptographically random secrets on first run; runs Alembic migrations; creates a Windows Desktop shortcut (`.lnk`) using the Wardress icon (§3) that opens `http://localhost:<port>` in the default browser; prints a clear "Wardress is running — open the shortcut on your Desktop" success message.
- **`update.ps1`**: `docker compose pull && docker compose up -d --build`, runs any new Alembic migrations automatically, prints what changed if a changelog file is present.
- Both scripts must be idempotent and safe to re-run, and must exit with a clear non-zero code and human-readable message on any failure — no silent failures.

---

## 11. What "as powerful as possible" adds beyond the minimum

- Multi-user RBAC (admin/analyst/viewer)
- Bulk site import (CSV / sitemap crawl)
- Adaptive scan intervals (scan faster right after a change is detected, back off when stable; optional business-hours-only scheduling)
- Point-and-click suppression rules on the live screenshot (§5)
- Remediation webhooks, manual-confirm by default (§9)
- Full audit log of every config change, baseline reset, and alert
- PDF/Markdown report export (§8)
- API keys + fully OpenAPI-documented REST API for scripting
- Operational health/status page (queue depth, scan latency, DB size, uptime)

---

## 12. Repository Layout (create this exact skeleton in Phase 0)

```
wardress/
├── PROGRESS.md                  # living memory file, appended every phase
├── WARDRESS_MASTER_PROMPT.md    # this file
├── DESIGN-resend.md             # design tokens (font-substituted per §4)
├── docker-compose.yml
├── .env.example
├── scripts/
│   ├── install.ps1
│   └── update.ps1
├── assets/brand/
│   └── wardress-logo.svg
├── backend/
│   ├── pyproject.toml / uv.lock
│   ├── app/            # FastAPI app
│   ├── worker/         # Celery tasks (detection layers live here)
│   ├── alembic/
│   └── tests/
├── frontend/
│   ├── package.json / pnpm-lock.yaml
│   ├── src/
│   └── tests/
├── reference/           # Phase 0 read-only clones (changedetection.io, etc.) — never imported into build
└── docs-cache/          # Phase 0 cached docs pages for offline reference
```

---

## 13. The Phase QA Pass (mandatory after every phase)

After a phase's implementation is "done" per the implementer's own assessment, run a full QA pass with this charter:

> Assume every file changed in this phase is wrong until you personally prove otherwise. Re-read every changed file fresh — do not trust the implementer's summary. Run the full test suite. Then actively reason through and (where testable in code) exercise the phase's failure modes: unreachable sites, timeouts mid-scan, Redis or Postgres unavailable, concurrent scans of the same site, non-UTF8 content, extremely large pages, sites that redirect infinitely, expired/self-signed TLS certs, a Gemini API key that's invalid or over quota, an SMTP server that rejects auth, a Telegram bot token that's revoked. Attempt every edge case you can think of specific to this phase's feature. Only report the phase clean if you cannot find a flaw after genuinely trying.

**Standing rule on framing and execution (decided 2026-07-16, Phase 1):**
All QA and testing work — including how it is reasoned about and described out loud — must use **neutral engineering language**: tests, edge cases, failure modes, validation, invariants, regression coverage. Do not frame or narrate QA as attacks, adversaries, exploitation, or similar security-attack storytelling. The QA pass runs **directly in the main session** — never delegated to a themed "adversarial"/"paranoid" subagent persona. And it must **never send live malformed/adversarial traffic against the running stack** (see carve-out below — that remains a manual user step every phase). This rule governs *framing and execution method only*: test coverage and rigor stay maximal, and every failure mode listed in the charter above must still be exercised wherever it can be tested in code.

**Carve-out (decided 2026-07-16, Phase 0 sign-off):** negative/malformed-input probing of the *running system* — unusual request paths, malformed/oversized headers, malformed request bodies, protocol-level abuse against the live API and services — is **not** performed by Claude Code. That category is a **manual step in the phase sign-off checklist**, executed by the user in a plain terminal outside Claude Code, for every phase. Claude Code should still write *unit/integration tests* for malformed-input handling in application code (parsers, validators, detection layers), but must not drive live malformed traffic at the stack itself.

The QA pass's findings — bugs found, fixes applied, edge cases now covered — get appended to `PROGRESS.md` before the next phase's kickoff prompt is written. If the pass finds unresolved issues, the phase is not complete; fix them and re-run the pass before proceeding.

**Phase sign-off checklist (every phase):**
1. Full automated test suites pass (backend + frontend).
2. Main-session QA pass (above, with the carve-out and the framing rule) reports clean.
3. **Manual negative/malformed-input QA by the user** (plain terminal, outside Claude Code) — user confirms done.
4. `PROGRESS.md` appended; next phase kickoff prompt generated.

---

## 14. Phased Roadmap

Build in this order. Each phase must end with: passing tests, a clean main-session QA pass (§13), an appended `PROGRESS.md` entry, and a generated "Phase N+1 Kickoff Prompt" for the user to paste into a new chat.

**Phase 0 — Foundations & offline readiness**
- Create the repo skeleton (§12)
- `uv`-managed backend project, `pnpm`-managed frontend project, both initialized
- Clone reference repos (read-only, `/reference/`): `dgtlmoon/changedetection.io`
- Pre-fetch/cache pinned package versions and documentation pages (§1, §2) into `/docs-cache/`
- Seed `PROGRESS.md` with the architecture decisions from this prompt (including the WeasyPrint-vs-Playwright PDF rationale, and the frontend static-serving decision from §1)
- Docker Compose skeleton with all services defined (even if empty/hello-world) and confirmed to build and start together
- CI skeleton: lint, `uv pip audit`/`pip-audit`, `pnpm audit`, test runner wired up

**Phase 1 — Thin end-to-end slice**
- Site CRUD (add/list/delete a monitored site) — API + minimal UI
- Baseline capture: HTML + screenshot + SHA-256 hash, stored to Postgres + local volume
- One manual "scan now" that re-fetches and computes only layer 1 (hash diff) — prove the full pipeline (frontend → API → Celery task → Playwright → DB → back to frontend) works end-to-end before adding any more detection sophistication
- Basic auth (login/JWT) wired in
- Logo drawn, design tokens applied to the shell layout and nav bar

**Phase 2 — Full detection engine**
- Implement all 9 detection layers (§5) with stored per-layer evidence
- Fused risk score + flagged/not-flagged threshold, configurable per site
- Celery Beat recurring scan scheduler with adaptive interval logic

**Phase 3 — SOC Dashboard UI**
- Visual diff slider, DOM diff tree viewer, threat scoring gauges, historical incident timeline (all per the Wardress-specific design additions in §4)
- Suppression-rule point-and-click UI
- Full reskin of every shadcn component against the design tokens — no default look anywhere

**Phase 4 — Notifications & Intelligence**
- Apprise integration (Email/Discord/Slack/ntfy/webhook), SMTP settings UI with test button
- Telegram bot (§8) with setup flow
- Gemini (`gemini-2.5-flash`) optional semantic layer + "Explain this incident" feature, with rate limiting and silent degradation
- Ollama optional local-LLM path
- PDF/Markdown report export via WeasyPrint

**Phase 5 — Advanced features & hardening**
- RBAC (admin/analyst/viewer), audit log, API keys, bulk site import
- Remediation webhooks (manual-confirm default)
- Security hardening pass: SSRF deny-list, rate limiting, secrets audit
- Operational health/status page

**Phase 6 — Installer, docs, polish**
- `install.ps1` / `update.ps1` finished and tested on a clean Windows machine with Docker Desktop
- README with the logo, screenshots, setup instructions
- Final full-system QA pass (§13) across every phase's functionality together, not just in isolation

At the end of each phase, produce a **"Phase N+1 Kickoff Prompt"**: a short, self-contained prompt block (reminding the new chat to read `WARDRESS_MASTER_PROMPT.md`, `DESIGN-resend.md`, and `PROGRESS.md` first) that the user pastes into a fresh Claude Code chat to continue. Do not skip this — it's how continuity across chats is maintained.

---

## 15. Definition of Done (applies to every phase, no exceptions)

- All tests pass, including the edge cases the QA pass added
- No hardcoded secrets, no TODOs left silently unresolved (either fix them or log them explicitly in `PROGRESS.md` as a known, deliberate deferral with a reason)
- Every new API endpoint appears correctly in the OpenAPI docs
- Every new UI surface matches the design tokens — nothing left in default shadcn/Tailwind styling
- `PROGRESS.md` updated
- Next phase's kickoff prompt generated
