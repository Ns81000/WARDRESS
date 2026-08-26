# TEMPLATE — Standing Instruction: How to Turn a User Request Into an Implementation Prompt

> **How you (the user) use this:** In any new chat, briefly describe the change or problem
> you want, and say something like *"use Prompts\Implementations\PROMPT-TEMPLATE.md"*.
> The agent will do all the deep reading and analysis FIRST, ask you about every decision
> that needs your input, wait for your explicit **"create the prompt"**, and only then write
> the final `PROMPT-00N-<slug>.md` into that folder — ready to paste into a fresh session.
>
> **What this prevents:** having to re-explain, in every future session, that the agent must
> read the protocols/logs, analyze the code deeply before writing any prompt, ask questions
> before creating it, and follow the house rules for tests/baselines/logging.

---

You are being asked to produce an implementation prompt for the WARDRESS project
(`C:\Users\Ns8pc\Music\WARDRESS`). You are NOT implementing anything yourself in this chat —
you are producing the prompt another fresh-session agent will execute. Follow these three
phases exactly, in order. Do not skip ahead. Do not create any prompt file before Phase 2
is fully satisfied.

## PHASE 1 — Mandatory intake reading + deep code analysis (always do ALL of this)

Before asking the user anything or proposing anything, read — completely, start to finish,
not skimmed:

1. `Prompts\WARDRESS_PARANOID_FIX_PROTOCOL.md` — its rules, Gauntlet Loop methodology (§2),
   fix-entry format (§3), and discipline standards apply to implementation efforts even when
   the work is a feature/restoration rather than a finding-fix. Adapt, don't abandon.
2. `Prompts\Implementations\IMPLEMENTATION_LOG.md` — the implementation log. Read every
   existing entry: prior runs' design decisions, residual risks, and "new leads" often
   directly affect your task (e.g., something already tried, something deliberately left
   open, a baseline that moved).
3. `Prompts\WARDRESS_FIX_LOG.md` — the completed defect-fix effort's log. You do NOT need to
   re-read all ~2800 lines blindly: search it for every entry touching your task's files and
   subsystems (grep filenames, component names, phase names) and read those entries IN FULL.
   The privacy tripwires, lint baselines, and test suites it established are permanent
   constraints on all future work. Pay special attention to:
   - Phase 27 (frontend data-honesty) — `no-third-party-image-hosts.test.ts` bans these
     literals anywhere under `frontend/src/**`: `google.com/s2/favicons`, `svgl.app`,
     `cdn.jsdelivr.net`, `cdn.simpleicons.org`, `api.iconify.design`, `models.dev/logos`.
   - The oxlint baseline (**exactly 0 errors / 12 warnings** unless a logged entry says it
     moved), tsc clean, vitest green, backend ruff clean, alembic-check-no-drift.
4. The ACTUAL current code for every file/subsystem your analysis touches — with `read_file`
   and `search_files`, tracing symbols to definitions and callers. Verify claims against the
   tree; never rely on memory or on what any log says the code looks like NOW. For frontend
   UI tasks: find every render site of the affected components (grep usages repo-wide), check
   adjacent markup contracts (e.g., Phase 28's stretched-link z-order in sites rows), and
   confirm payload/type shapes in `lib/api.ts` and backend `schemas.py`. For backend tasks:
   check auth dependencies, settings-store patterns, migration conventions in
   `alembic/versions/`, existing test harness conventions (`tests/db_harness.py`,
   `conftest.py`), and whether similar primitives already exist (reuse the codebase's own
   idioms — atomic claims, SSRF gate, limiter calls, record_audit).
5. If the user supplied assets (SVGs, files): inspect them for safety and suitability
   (viewBox/dimensions present, no scripts/external refs, size sane) BEFORE planning around
   them.

Record internally (not yet shown to the user as a prompt): root causes, every render/call
site affected, every constraint in play, every edge-case category from Gauntlet §2 Step 3
that will apply, and which existing baselines/tests could break.

## PHASE 2 — Clarify with the user BEFORE creating anything (mandatory)

Do not create any prompt file yet. First, present the user with:

- A short plain-language summary of what you found in the code (including anything that
  contradicts or complicates their request).
- Your proposed approach per workstream, in simple language, including the tradeoffs.
- Every open decision that genuinely needs THEIR choice — e.g.: default ON vs OFF for a
  setting; which asset/variant to use; how broad coverage should be; visual/placement
  preferences; whether borderline scope belongs in this run or a later one; anything where
  two defensible designs exist.
- Anything you could NOT verify or that seems impossible/conflicting — surface it honestly
  now, never bury it in the prompt.

Iterate with the user: answer questions, adjust the plan, re-present. Keep going until the
user has had every concern satisfied and EXPLICITLY says some form of **"create the
prompt"** / "ok go". Only then move to Phase 3. (If the user pre-answers everything in
their first message AND explicitly tells you to proceed without questions, you may skip
straight to Phase 3 — but silence is never consent.)

## PHASE 3 — Create `PROMPT-00N-<slug>.md` in this folder

Numbering: highest existing `PROMPT-0NN-*` number + 1 (`ls` the folder). Slug: short,
lowercase, hyphenated. The generated prompt MUST contain, in this order:

1. **Read-first block** — instructing the executing agent to completely read, before any
   work: this template's Phase-1 reading list adapted to the task (protocol file,
   IMPLEMENTATION_LOG.md entries, the relevant WARDRESS_FIX_LOG.md entries by grep, plus
   every file it will edit and its neighbors), and stating plainly that there is no
   findings file for implementation runs — the prompt itself is the spec, and if any claim
   in it proves wrong against the real tree, the agent does the right thing instead and
   logs the deviation.
2. **Background** — why the change exists, tied to whatever history applies (e.g., Phase 27
   rationale, prior IMPLEMENTATION_LOG entries), written so a cold-context agent understands
   the constraints' origin.
3. **Hard constraints (NON-NEGOTIABLE)** — always include, verbatim-adapted:
   - `no-third-party-image-hosts.test.ts` unmodified/passing; zero runtime third-party
     requests; no remote URLs in `src/` (even comments).
   - No weakening of any existing test; additive extension only.
   - Baselines: oxlint exactly **0 errors / 12 warnings** (or the current logged value),
     tsc exit 0, vitest fully green, `pnpm build` success, backend pytest green at-or-above
     the recorded baseline, ruff check + format clean, `alembic check` no new drift.
   - Tooling: pnpm exclusively (npm/yarn/bun OS-blocked); Python via uv/project venv only
     (pip blocked); git-bash POSIX syntax in shells.
   - No drive-by refactors; match existing style; read-before-edit; trace symbols; no
     invented APIs/files/imports.
4. **Per-workstream specs** — each broken into concrete numbered steps with: exact target
   files and line references verified against the current tree, the chosen design (from
   Phase 2 agreement) INCLUDING rejected alternatives worth recording, full edge-case
   obligations (concurrency/races, empty/null/malformed/oversized input, unicode/IDN,
   partial failure mid-operation, retry/idempotency, auth/RBAC, interaction-with-prior-fixes,
   backward compatibility, performance, fix-failure mode), and explicit "do not disturb X"
   warnings for fragile adjacent contracts discovered in Phase 1.
5. **Test obligations** — every workstream gets automated tests placed in the proper existing
   location/convention; hermetic only (no live network/DNS in CI); failing-before proof
   required per protocol style (collection-failure acceptable for brand-new modules;
   stash-proof for behavior changes); concurrency tested against the REAL Postgres harness
   with barrier/shim patterns, clock injection instead of sleeps.
6. **Verification gate** — the exact commands to run and the pass criteria for each, plus a
   manual smoke checklist appropriate to the change (and the rule: if containers aren't up,
   ASK the user to start them — never run install scripts unprompted).
7. **Rules of engagement** — commits in conventional style, one per workstream plus docs,
   NO push; scratch probes outside the repo, deleted after; honest reporting of every gate's
   actual result and every deliberate deviation.
8. **Log discipline** — the FINAL mandatory step: append a complete entry to
   `Prompts\Implementations\IMPLEMENTATION_LOG.md` using that file's entry format, filling
   EVERY field honestly (design decisions, constraints honored, edge cases handled, tests
   added with failing-before notes, exact regression numbers, manual verification, residual
   risk, new leads, commits).
9. **Docs honesty clause** — if the change alters any behavior described in README/docs
   (privacy wording, feature claims), surgical doc updates following the verifiable-copy
   discipline (no absolutes, no constants pinned in prose).

Then show the finished prompt path to the user and stop. Do not begin implementing it in
this chat unless the user explicitly asks you to run it here too.

---

### Quality bar (what "done" means for the prompt you produce)

A cold-context agent receiving ONLY the repo + your generated prompt should be able to
execute the whole thing correctly without asking the user anything — because every fact you
learned in Phase 1, every decision made in Phase 2, every constraint, edge case, test site,
and gate is written down in it. If executing agents would need to re-discover something you
already know, your prompt is not done yet.
