# WARDRESS — Final Paranoid Audit & Hardening Pass

> **How to use this file:** Paste this entire file as your next prompt into Claude Code,
> in the WARDRESS repo root (`C:\Users\Ns8pc\Music\WARDRESS`), alongside the existing
> `WARDRESS_MASTER_PROMPT.md`, `DESIGN-resend.md`, and `PROGRESS.md`. This is a single,
> self-contained pass. Do not skip any section of this file. Do not summarize this file
> back to me before starting — start working.

---

## 0. What this pass is

This is the **final audit-and-report pass** before Wardress is treated as release-ready.
It is **not** an implementation phase. Your job in this pass is to:

1. Establish ground truth (what actually exists vs. what is merely documented or claimed).
2. Read and test literally everything — backend, frontend, infra, installer, docs, UI/UX —
   with zero trust in existing comments, docstrings, tests, or prior `PROGRESS.md` claims.
3. Produce one comprehensive markdown report cataloguing every finding, major to minor.
4. Produce a second, short "Implementation Kickoff Prompt" for a **fresh chat** that will
   read the report and fix everything in it.

You do **not** fix behavioral bugs, logic issues, or UI issues in this pass. You catalogue
them. The only work you do directly in this pass is **safe, unambiguous housekeeping**:
removing files that are provably dead/orphaned (zero references anywhere in code, config,
docs, or scripts) and applying pure auto-formatting (linters/formatters) that changes no
behavior. Everything else — every real bug, gap, or design deviation — goes in the report
for the next session to implement, so you never have to hold the whole fix-set in context
at once.

---

## 1. Ground truth first — before opening a single subagent

Before delegating anything, do this yourself, in the main session:

1. Read `WARDRESS_MASTER_PROMPT.md` in full — every section, §0 through §15.
2. Read `DESIGN-resend.md` in full — every token, component spec, do/don't, and the
   responsive/breakpoint tables.
3. Read `PROGRESS.md` in full, start to finish, including the **"Post-completion: live key
   configuration + Gemini model fix"** entry at the very end. That entry is the authoritative
   current state of the project — Phases 0 through 6 are complete and signed off, real
   `GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN` values are already configured and were
   live-verified, and the `gemini-2.5-flash` → `gemini-flash-latest` fix already shipped.
   If any other document, memory, or your own assumption conflicts with what `PROGRESS.md`'s
   last entries say, `PROGRESS.md` wins.
4. Run `git log --oneline -30`, `git status`, and `git remote -v`. Confirm the local tree
   is clean (or note exactly what's uncommitted) and confirm the GitHub remote
   (`https://github.com/Ns81000/WARDRESS`) matches what you expect. Use the GitHub repo as
   a secondary source of truth if anything about local history looks inconsistent — you may
   fetch/compare against it, but do not push anything during this pass.
5. Search the full git history (`git log -p` / `git grep`, not just the working tree) for
   anything resembling a committed secret, API key, or credential. Confirm `.gitignore`
   actually excludes `.env`, build artifacts, `node_modules`, virtual envs, and Docker
   volumes.
6. Produce a real, current repository tree (e.g. `git ls-files` grouped by directory) and
   diff it mentally against the skeleton in Master Prompt §12. This tree is what you'll use
   to carve up subagent work in §4 below — don't guess at file names, use what's actually
   there.

Do not proceed to subagent work until you have done all six of the above yourself.

---

## 2. Standing rules for this entire pass

These are not new — they're the project's own established conventions
(Master Prompt §13, and the security/fail-safe rules in §0/§9). Carry them forward exactly:

- **Neutral engineering language, always.** Describe and reason about all testing —
  including your own internal reasoning, not just what you tell subagents — in terms of
  tests, edge cases, failure modes, validation, and invariants. Never frame QA work as
  attacking, breaking, or exploiting anything.
- **Never send live malformed/adversarial traffic at the running stack from inside this
  session.** Unusual paths, malformed headers, malformed bodies, protocol-level abuse
  against the live API — that category stays a manual step I run myself, outside Claude
  Code, in a plain terminal (see §5). You can and should still write/extend automated
  unit and integration tests that exercise malformed-input *handling in code* (parsers,
  validators, schema rejection) — that's normal test coverage, not live traffic.
- **Never assume a library's behavior — verify it**, exactly as Master Prompt §0 Rule 1
  requires, especially for anything you're re-checking that a prior phase already "verified."
- **Fail-safe first.** Anywhere you find a code path where a third-party failure (Gemini
  quota, SMTP auth rejection, Telegram token revoked, Redis/Postgres down, an unreachable
  scan target) could crash a scan or corrupt state instead of degrading gracefully, that's
  a **critical** finding regardless of how unlikely it seems.
- **Real keys exist — use them for live verification, don't just read the code.** `.env`
  already has a working `GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN` (see the `PROGRESS.md`
  post-completion entry). Use them to run real end-to-end checks: an actual "Explain this
  incident" call, an actual Telegram bot command round-trip, an actual delivered alert.
  Never print, log, or write the raw key/token values anywhere, including in the report —
  reference them only as "configured" / "present" / "working," matching the project's
  existing secret-redaction convention. Be economical with live Gemini calls (a handful of
  real round-trips to prove each code path is enough — don't run a load test against a
  free-tier quota). If SMTP credentials are *not* configured in `.env`, say so explicitly
  in the report and note that email-path verification was limited to the graceful-failure
  case; don't invent SMTP credentials.
- **No fixes for real bugs in this pass** — document them (§6). The only exceptions are
  unambiguous dead-file removal and pure formatting, as described in §0.

---

## 3. Subagent strategy — how to actually stay paranoid without blowing your context

You must delegate almost all of the reading and testing work below to subagents, each with
a **narrow, bounded scope**: a handful of closely-related files, or one feature slice, per
subagent — never "review the backend" as a single task. This is not optional; it's the only
way to read every line of a project this size without losing earlier findings to context
pressure.

For every subagent you launch:
- Give it the exact file(s)/directory it owns, and nothing else to roam into.
- Tell it explicitly: *read every line, don't skim, don't trust comments/docstrings/tests
  written by prior sessions as proof of correctness — verify behavior yourself.*
- Have it return a **compact, structured finding list** back to you — not a full transcript
  of what it read. Each finding: file path, line number(s), severity, one-paragraph
  description, and (if obvious) a suggested fix direction. No fix implementation.
- If a subagent's scope turns out to be too big to finish without running low on its own
  context, have it stop, report what it covered and what's left, and split the remainder
  into a follow-up subagent — never let a subagent silently cut corners to fit.

You (the orchestrator) accumulate every subagent's findings into the single report from §6.
Re-launch waves as needed; there's no cap on how many subagents this takes.

---

## 4. The audit surface

Work through these waves in order. Within each wave, split the listed scope into as many
small subagent tasks as the actual file count warrants — the groupings below are a floor,
not a ceiling.

### Wave A — Inventory & structure
- Enumerate every tracked file. Classify each as: core (referenced/imported/used),
  generated (rebuildable, shouldn't be tracked if it currently is), reference-only
  (`/reference/`, `/docs-cache/` — confirm nothing under these was ever imported into the
  real build, per Master Prompt §1 Rule 1's spirit), or **orphaned** (no reference from any
  other file, script, doc, or config).
- Cross-check the real tree against the Master Prompt §12 skeleton. Flag anything that's
  drifted from that layout without a documented reason in `PROGRESS.md`.
- For orphaned files you're fully confident about (truly zero references anywhere,
  including in scripts and docs) — delete them now and log exactly what and why in the
  report. For anything ambiguous, leave it and flag it for the next session instead of
  guessing.
- Check for stray secrets, `.env` files, or credential-shaped strings anywhere in the tree
  that aren't the gitignored `.env`.

### Wave B — Backend (one subagent per bullet, or smaller if a bullet covers many files)
Re-verify all of this from scratch against the actual code, not the `PROGRESS.md`
narrative that already describes it as done:
- Auth: Argon2id hashing, JWT issuance/expiry, refresh-token rotation, reuse/theft
  detection and family revocation, cookie flags (`COOKIE_SECURE` behavior in both modes).
- RBAC: every endpoint's `require_roles` usage — confirm admin/analyst/viewer boundaries
  match Master Prompt §9/§11 and the Phase 5 decision that settings/channels are
  admin-only, with no endpoint silently missing a dependency.
- SSRF protections: the deny-list, DNS-resolution/redirect re-checks, the
  `SSRFPinningTransport` for raw `httpx` calls, and Playwright's separate post-redirect
  guard — confirm they still actually gate every code path that fetches a target site
  (not just the ones they were originally written for).
- All 9 detection layers (§5 of the master prompt): confirm each one's scoring/evidence
  logic, the cheap-gates-expensive skip logic (and that skips are logged), and that a
  failure in any single layer can't take down the whole scan.
- Celery tasks + Beat: baseline capture, scan-now, the adaptive scheduling logic, the
  dispatch heartbeat, and the orphan-artifact janitor — confirm idempotency under
  concurrent triggers and correct behavior when Redis/Postgres is briefly unavailable.
- Notifications: Apprise integration, the Telegram bot's command set
  (`/status /sites /scan /ack /mute /help`), SMTP send path, and per-delivery status
  tracking — confirm every channel degrades silently on failure rather than blocking a scan.
- Gemini/Ollama: confirm the `gemini-flash-latest` default is used everywhere (not a stray
  leftover `gemini-2.5-flash` reference anywhere in code, config, or docs), the rate
  limiter/backoff, the ambiguous-band escalation logic, and silent degradation when the key
  is missing/invalid/quota-exhausted.
- Reports: WeasyPrint PDF and Markdown export — actually generate one of each against real
  data and open/inspect the PDF (page breaks around tables/images, headers/footers,
  embedded diff thumbnails), don't just confirm the endpoint returns 200.
- Remediation hooks: manual-confirm default, the confirm-queue behavior including the
  already-documented stuck-state fix, encrypted-at-rest webhook URLs, and that a hook
  failure can never affect a scan.
- Bulk import: CSV and sitemap paths, the per-row result contract, the row/size caps, and
  per-row SSRF checks.
- Audit log: confirm coverage is actually complete against the list in `PROGRESS.md`
  (every mutation type claimed), confirm the redaction rule against fresh eyes — try to
  find a config shape that would leak a secret into an audit row.
- Health endpoints: confirm every probe genuinely degrades to a labeled status instead of
  a 500 when its dependency is down.
- Database/migrations: run the full upgrade path from empty to head, then a downgrade,
  then upgrade again, and confirm it's still clean. Check for any model field with no
  matching migration, or any migration that doesn't match the current model state.
- Rate limiting / CORS: confirm the fixed-window limiter behavior under real concurrent
  requests, and that CORS is genuinely locked down by default.
- API surface completeness: every endpoint listed in Master Prompt §7 actually exists,
  is tagged and described in OpenAPI, and returns sensible error shapes.

### Wave C — Frontend (one subagent per page/feature area)
- App shell, nav bar, routing, and auth flows (login, token refresh, logout, session
  expiry handling).
- Sites list/add/delete/bulk-import UI.
- Site detail: baseline view, scan history, live scan polling, rebaseline.
- SOC dashboard visuals: visual diff slider, DOM diff tree viewer, threat scoring gauges,
  historical incident timeline.
- Suppression-rule point-and-click UI.
- Settings screens: notifications/channels, SMTP, Telegram, Gemini/Ollama, each with its
  test-button flow actually exercised.
- Users/RBAC management, API keys, audit log page, remediation confirm queue, health page.
- For every page: confirm loading states, empty states, and error states all exist and are
  designed (not just a bare spinner or blank screen), and that nothing silently fails with
  no user-visible feedback.
- TanStack Query usage: stale/loading/error states handled consistently; no unhandled
  promise rejections; no query that can spin forever on a dead endpoint.

### Wave D — UI/UX design-fidelity (treat this like a professional design review, not a
functional QA pass — go component by component with `DESIGN-resend.md` open)
For every screen and every component, check:
- **Color discipline**: true `#000000` canvas everywhere it should be (not a near-black
  substitute), accent glows used only as low-opacity radial washes and never as solid
  fills/buttons, threat-state colors (clean/investigating/confirmed) mapped correctly and
  the confirmed-red state used sparingly and locally, not as a page-wide wash.
- **Typography lane discipline**: Fraunces only in the display/headline role at
  `line-height: 1.0`, Instrument Sans only in its assigned role, Inter only in UI/body
  roles, Geist Mono only in code contexts — flag any place a font is used outside its
  assigned lane, and any place weight is bumped for emphasis instead of a family change.
- **Elevation**: hairline borders (6%/14% translucent white) doing the elevation work,
  zero drop shadows anywhere.
- **Radius scale**: `rounded.lg` (12px) on cards, `rounded.md` (8px) on buttons/inputs,
  `rounded.full` on pills/avatars/status dots — flag any inconsistent radius usage.
- **Spacing/whitespace**: check actual pixel values against the spacing scale in
  `DESIGN-resend.md`, not eyeballed — look for cramped or inconsistent padding, misaligned
  grids, and boxes that are too tight or oddly oversized relative to their content and
  neighbors. Look specifically for "one white surface per viewport" violations.
- **Component reskin completeness**: every shadcn component actually reskinned — hunt for
  any control (dropdown, dialog, toast, tooltip, table, checkbox, etc.) that's still
  wearing default shadcn/Tailwind styling instead of the Wardress tokens.
- **Interactivity and feedback**: hover/focus/active states on every clickable element,
  visible focus rings for keyboard navigation, transitions that feel intentional rather
  than either absent or gratuitous, and consistent `lucide-react` icon sizing/stroke-width
  throughout (no icon that looks like it wandered in from a different set).
- **No emoji, no decorative icons without semantic meaning, anywhere** — including in
  generated PDF/Markdown reports and Telegram bot messages.
- **Responsive behavior**: manually check every breakpoint in the `DESIGN-resend.md` table
  (Desktop XL down to Mobile ≤425px) for the dashboard's own layouts (nav collapse, grid
  reflow, touch targets ≥36px desktop / 44px mobile, text-input height scaling) — the SOC
  dashboard has its own layouts beyond the original marketing-site doc, so verify those
  specifically, they're not pre-specified anywhere.
- **Accessibility basics**: color contrast on body/mute/ash text against the true-black
  canvas, alt text or aria-labels on icon-only buttons, form inputs with associated labels.

### Wave E — Installer / Updater / Infra / Docs
- Re-run `install.ps1` yourself, twice in a row, to genuinely re-verify idempotency (don't
  trust the "tested three ways" claim in `PROGRESS.md` — reproduce it). Check: Docker
  Desktop-not-running error message is clear and actionable, `.env` secret generation is
  cryptographically sound and never reuses a default, Alembic migrations run, the desktop
  shortcut is actually created with the correct icon (verify the `.ico` file it points to
  matches `assets/brand/`), and the shortcut actually opens the running app at the right
  URL/port.
- Re-run `update.ps1` against a running stack. Confirm the standing beat-container
  force-recreate gotcha is still handled, data/artifacts/`.env` survive, and new migrations
  apply automatically.
- Read `docker-compose.yml` end-to-end: every service's healthcheck, every env var it
  needs is actually passed through (re-check the Phase 6 finding about `RATE_LIMIT_*` /
  `TRUST_PROXY_HEADERS` / `CORS_ALLOWED_ORIGINS` / `COOKIE_SECURE` not reaching the
  container — confirm it's genuinely still fixed and nothing since has regressed it),
  volumes are correctly scoped, and no service is missing from the intended set in Master
  Prompt §1's Infrastructure table.
- **README accuracy pass**: don't assume the user needs Python/uv/Node/pnpm on their host
  machine — trace exactly what `install.ps1`/`update.ps1` actually require to be present
  on Windows *before* Docker takes over, versus what only ever needs to exist inside the
  built images. Document only the real prerequisites, each with an official download link
  and a one-line command to verify it's installed correctly (e.g. `docker --version`,
  `git --version` if cloning from GitHub is part of the flow). Don't add unnecessary host
  installs just because they're common in other Python/Node projects — if this project's
  actual install path is "clone the repo, run `install.ps1`, Docker does the rest," the
  README should say exactly that and nothing more.
- Confirm the README's screenshots, feature list, `.env` reference table, and role table
  still match current reality (not what an earlier phase looked like).
- Confirm `CHANGELOG.md` (if present) is wired into `update.ps1`'s "print what changed"
  behavior as described in Master Prompt §10.

### Wave F — Cross-cutting
- **Dead code & dependencies**: unused imports/functions/components, unused npm/pip
  packages, and confirm zero commercial/paid fonts or assets anywhere in the repo (only
  OFL/Google Fonts/Apache/MIT), per Master Prompt §0 Rule 4.
- **Performance**: N+1 query patterns, missing indexes on frequently-filtered columns
  (site_id/created_at style lookups), any blocking/sync I/O sitting inside an async path,
  and any obviously expensive operation that runs on every scan instead of being
  gated/cached.
- **Test-suite quality, not just pass/fail**: sample a cross-section of the 383 backend +
  25 frontend tests and judge whether they actually assert meaningful behavior or are
  shallow/tautological. Identify at least the top handful of real code paths (auth edge
  cases, SSRF edge cases, notification failure paths, detection-layer edge cases) that
  currently have **no** test coverage at all, and list them explicitly.
- **Documentation drift**: spot-check a sample of `PROGRESS.md`'s specific claims
  ("62 routes, every one tagged and described," "23 orphan directories removed," etc.)
  against the actual current repo state, since some time and at least one post-completion
  change have passed since those were written.
- **Security posture re-check**: secrets audit (no hardcoded creds, nothing in logs or
  audit rows), dependency audit tools (`pip-audit`, `pnpm audit`) re-run fresh, not
  trusted from memory.

---

## 5. Live verification — what you do yourself vs. what needs me

Do as much as you genuinely can yourself — you have real terminal access to this repo and
a running (or startable) Docker Compose stack. Only hand things to me when they truly
require a human or a physical machine: actually seeing the desktop shortcut appear and
double-clicking it, actually receiving a Telegram message on a phone, a true from-scratch
install on a genuinely clean machine, or visually judging whether a rendered screen looks
right rather than just whether it returns the correct DOM/JSON. Where you do hand something
to me, follow this exact pattern so it costs me as little effort as possible:

1. Give me the **exact command(s)** to paste, one block at a time, with a one-line
   explanation of what each one checks and what a "clean" result looks like.
2. I'll run them and paste the output back to you as-is.
3. You fold the result straight into the report (§6) — a pass, a fail with a new finding,
   or a note that something needs a follow-up command — and only then give me the next
   block, if any.

The standing manual negative/malformed-input probing against the live stack (§2, and the
project's existing convention) is still mine to run, exactly as before — include a fresh,
up-to-date set of `curl` probes covering every endpoint added or changed since the last
manual pass, as part of this same handoff pattern.

Don't ask me anything you can determine yourself by reading code, running the stack, or
running the test suites.

---

## 6. The deliverable: `WARDRESS_AUDIT_REPORT.md`

Write this to the repo root as you go (don't hold the whole thing in memory until the end —
append to the file after each wave finishes, so nothing is lost if context runs low).
Required structure:

```markdown
# Wardress — Final Audit Report (<date>)

## Executive summary
- One paragraph: overall state, total findings by severity, is this release-ready.

## Methodology
- Waves run, subagent count, live verification performed, what still needs my manual pass.

## Findings

Each finding as its own entry:

### [SEVERITY] Short title
- **Area:** backend / frontend / ui-ux / infra / docs / performance / test-coverage
- **Location:** exact file path(s) and line number(s)
- **What's wrong:** concrete description, not a vague impression
- **Evidence:** what you read/ran/saw that proves this — a test you ran, a code path you
  traced, a screenshot description, an actual output
- **Suggested fix direction:** enough for the next session to act on, not a full patch
- **Status:** open / fixed-now (housekeeping only) / needs-user-decision

Severity scale:
- **Critical** — data loss, security gap, scan pipeline crash/corruption, install/update
  breakage
- **High** — a real user-facing bug or a design-system violation visible on first use
- **Medium** — edge case gap, missing test coverage on a meaningful path, minor perf issue
- **Low / Polish** — cosmetic, spacing, wording, non-blocking optimization opportunity

## File inventory changes
- Files deleted this pass, and why each was safe to delete.
- Files flagged as likely-dead but left in place pending a decision (with reasons).

## UI/UX audit notes
- Findings not already captured above that are broader design-review observations
  (e.g. "the settings screens feel visually inconsistent with the dashboard screens as a
  set" — pattern-level notes, not just single-component bugs).

## Installer/updater verification log
- What you actually ran, the real output, what still needs my hands-on confirmation.

## Prerequisites verified for README
- The real, traced list of what a user needs installed on Windows before running
  `install.ps1`, each with its official link and verification command.

## Outstanding manual checks for me
- The exact command blocks from §5, in order, ready to paste.

## Completion checklist (see §7)
```

---

## 7. Completion gate — don't call this done until all of this is true

- Every tracked file in `backend/`, `frontend/src/`, `scripts/`, and the repo root has been
  read by at least one subagent (cross-check this against the inventory from Wave A —
  literally confirm nothing was skipped).
- Every requirement in Master Prompt §1 through §15 has been checked against real,
  re-verified behavior at least once in this pass — not accepted on `PROGRESS.md`'s word.
- Every UI screen has had a Wave D-style design-fidelity pass, not just a functional one.
- `install.ps1` and `update.ps1` have both been re-run for real in this session.
- The report has at least one entry in every "Area" category from §6, even if some are
  "no findings, verified clean."
- The report and any housekeeping deletions are committed to git with a clear message (do
  not push — that's mine to review first).

Only once all of the above is true, move to §8.

---

## 8. Second deliverable: the Implementation Kickoff Prompt

Once the report is complete, write a short, self-contained "kickoff prompt" block —
following the exact convention already used at the end of every phase in `PROGRESS.md`
(e.g. "Phase 6 Kickoff Prompt") — that I can paste into a **fresh** Claude Code chat to
implement every open finding. It must:

- Tell the new session to read `WARDRESS_MASTER_PROMPT.md`, `DESIGN-resend.md`,
  `PROGRESS.md`, and `WARDRESS_AUDIT_REPORT.md` in full before touching anything.
- Instruct it to work through the report's findings **grouped and prioritized by severity**
  (critical → high → medium → low), using the same small-subagent-per-task pattern from §3
  of this file so it doesn't run out of context either.
- Make this an explicit, non-negotiable completion requirement: **every single finding in
  the report — Critical, High, Medium, and Low/Polish alike — must end in one of two
  states: implemented, or individually and explicitly deferred with a stated reason logged
  in `PROGRESS.md`** (matching the project's existing "deliberate deferrals, not bugs"
  convention). Low severity is not license to skip a finding silently — it only affects
  the order it's worked in, not whether it's ever accounted for. The implementation pass
  is not complete while any finding is simply unaddressed and unmentioned.
- Any finding marked `needs-user-decision` in the report must be surfaced to me as an
  actual question, with the tradeoffs laid out, **before** any code is written for it — it
  does not get auto-resolved either toward "implement" or "defer" on the model's own
  judgment.
- Instruct it to run the same kind of full QA pass (Master Prompt §13) after implementing
  each severity group, before moving to the next, and to append its own results to
  `PROGRESS.md` when finished, matching the project's existing convention.
- Remind it that the manual negative/malformed-input QA step and the neutral-framing rule
  (§2 of this file) are permanent, standing project policy, not something specific to this
  pass.

Put this kickoff prompt at the very end of your final message to me, clearly marked, so I
can copy it straight into the next chat.

---

## 9. Reminders

- This pass is about finding and documenting reality, not defending prior work — if
  something `PROGRESS.md` marked "signed off" turns out to be broken, say so plainly.
- Thoroughness beats speed here. There's no reward for finishing fast — there's a real cost
  to missing something.
- Keep every subagent task small. If you notice yourself about to give one subagent more
  than a handful of files or more than one feature slice, split it.
