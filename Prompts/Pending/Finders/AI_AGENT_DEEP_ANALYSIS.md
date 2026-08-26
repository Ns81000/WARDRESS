# WARDRESS — AI Agent & AI Provider Layer: Deep Architecture Analysis

> Scope: every line of the AI subsystem, backend and frontend — the agent engine,
> tool registry, guard, context management, the unified provider layer (litellm),
> the models.dev catalog pipeline, Ollama integration, escalation, Telegram surface,
> Settings API/UI. Written from source reading, not documentation trust. Every claim
> cites `file:line`.

---

## 1. Executive Summary

The AI stack is a **two-task, any-provider, tool-calling agent** built on a single
`litellm.Router` call-site with a hand-rolled (but small and auditable) agent loop.
The design is unusually disciplined for this scale: RBAC is enforced in code rather
than prompt, high-impact actions are frozen-then-confirmed with atomic claim
semantics, prompt-injection containment is enforced structurally (fencing +
code-level auto-exec suspension), and every failure path degrades silently so AI can
never break scanning.

That said, deep inspection found **real flaws**, concentrated in exactly the place
you suspected: **the tool-calling capability mechanism**. It has *three independent
sources of truth* that can disagree, two of the catalog's provider types
(Azure/Bedrock/Vertex) are effectively unconfigurable through the UI, the agent-chat
fallback model bypasses the tool gate entirely, and there are several correctness,
cost-safety and UX gaps detailed below.

**Severity legend:** 🔴 P0 = broken/incorrect behavior today · 🟠 P1 = likely
production incident or cost/security risk · 🟡 P2 = robustness/correctness debt ·
🔵 P3 = enhancement / polish.

---

## 2. Complete Architecture Map

### 2.1 Backend modules (the whole AI graph)

| Module | Role |
|---|---|
| `backend/app/llm.py` | **The single LLM call-site.** Resolves an AI task → cached `litellm.Router`; key rotation = one deployment per API key; cross-provider fallback via Router `fallbacks`; secret scrubbing; prompt builders; strict-JSON classification parser (`llm.py:283-359`) |
| `backend/app/ai_catalog.py` | models.dev catalog sync (live → keep-existing → bundled snapshot), normalization, idempotent full-refresh upsert, `model_supports_tools` lookup (`ai_catalog.py:209-243`) |
| `backend/app/ai_config.py` | Provider CRUD service: Fernet credential encryption, key hints, SSRF validation of `base_url`, task assignment service, **assignment-time tool-calling gate** `resolve_tool_capability` (`ai_config.py:227-250`) |
| `backend/app/ai_ollama.py` | Native Ollama client: `/api/tags` discovery, `/api/show` capability probe (tool detection), streamed `/api/pull`; local vs Ollama Cloud (`ollama.com`, Bearer) (`ai_ollama.py:58-111`) |
| `backend/app/ai_startup.py` + `ai_migration.py` | Lifespan bootstrap: one-time legacy Gemini/Ollama migration → new tables; fresh-install seeding of an enabled local Ollama provider guarded by `ai_seed_done` sentinel (`ai_migration.py:57-150`) |
| `backend/app/agent/engine.py` | The turn loop: bounded (5 iterations) tool-calling loop, OpenAI-style message protocol, result bounding, untrusted-output containment flag, event stream (`engine.py:221-409`) |
| `backend/app/agent/tools.py` | 19-tool registry with `tier` (0 read / 1 safe / 2 high-impact / 3 destructive) and `min_role`; executors call the same services as REST routers; `fence_untrusted` marker defanging (`tools.py:88-104`) |
| `backend/app/agent/context.py` | 12-message window + rolling summary compression; ~250-token system instruction containing the injection rules and `<<<UNTRUSTED-DATA-*-…>>>` convention (`context.py:26-60`) |
| `backend/app/agent/guard.py` | Confirm-before-execute: freeze args verbatim into `agent_pending_actions`, TTL 10 min, supersede-per-conversation, atomic conditional-UPDATE claim on confirm (`guard.py:80-158`) |
| `backend/app/routers/agent.py` | Web surface: SSE streaming turn endpoint, conversation CRUD (50/user cap), confirm/cancel endpoints (`agent.py:139-191`) |
| `backend/app/routers/settings.py` (`ai_router`) | Admin config API: catalog providers/models, provider CRUD+validate, Ollama model listing/pull proxy, task assignment PUT with the agent-chat tool gate (`settings.py:601-915`) |
| `backend/app/explain.py` | Cached scan explanation (per-scan row cache), evidence-note extraction from all 8 layers |
| `backend/app/llm_escalation.py` → `worker/llm_escalation.py` | Ambiguous-band ([0.40, 0.75)) semantic second opinion; can only *raise* verdicts; confidence ≥ 0.6 required (`worker/llm_escalation.py:37-41`) |
| `backend/worker/telegram_bot.py` | Second agent surface: same `run_turn`, "acts-as" RBAC user link, inline Confirm/Cancel keyboard (`telegram_bot.py:496-604`) |
| `backend/worker/beat_tasks.py` | Celery beat: model-catalog refresh (12 h), pending-action expiry janitor (5 min) (`beat_tasks.py:308-324, 393-446`) |

### 2.2 Data model

```
ai_providers (uuid, label, provider_type, credentials_encrypted{api_keys[]},
             base_url, enabled, validation_status/detail/at)
ai_task_assignments (task PK ∈ {explanation, agent_chat},
                     provider_id CASCADE, model_id,
                     fallback_provider_id SET NULL, fallback_model_id)
model_catalog_providers (models.dev provider rows)
model_catalog_entries ("provider/model", tool_calling, reasoning,
                       context_window, max_output_tokens, cost_in/out)
agent_conversations (user_id CASCADE, surface web|telegram, title, summary)
agent_messages (role user|assistant|tool, content, tool_name, tool_payload JSON)
agent_pending_actions (conversation_id, user_id, tool, args JSON, summary,
                       status pending|confirmed|cancelled|expired, expires_at)
```

### 2.3 Request flows

**A. Chat turn (web):**
```
assistant.tsx send() → POST /api/agent/conversations/{id}/messages (fetch-stream, Bearer)
→ run_turn():
    persist user msg → resolve_task("agent_chat") → supports_tools? → tools_for_role(role)
    build system instruction + window(+summary) + user msg
    ≤5 × router.acompletion(messages, tools, tool_choice="auto")
      ├─ no tool_calls → final text → persist → maybe_title → maybe_summarize → done
      ├─ tier≥2 or untrusted-contaminated tier≥1 → create_pending() → "confirm" event → STOP
      └─ execute tier 0/1 inline → bounded result → persist tool row → feed back
SSE frames {type: tool|confirm|done|error} → assistant.tsx handleEvent()
```

**B. Provider resolution:** `resolve_task` reads `ai_task_assignments` → loads
provider (+fallback) → signature over `(task, provider.id, updated_at…, model_id)`
→ LRU cache hit returns shared Router (cooldown state persists) → miss builds
Router outside lock, double-check insert under lock (`llm.py:313-359`).

**C. Assignment-time tool gate (Settings):**
```
PUT /api/settings/ai/assignments/agent_chat
→ resolve_tool_capability(provider, model):
    ollama            → live GET/POST /api/show, look for "tools" in capabilities
    openai_compatible → None (trusted, never blocked)
    else              → models.dev catalog flag (provider_type/model_id)
→ refuse only when explicitly False (settings.py:821-829)
```

**D. Runtime tool-capability flag (engine):**
```
_supports_tools(provider_type, model_string)          # llm.py:235-252
    ollama | openai_compatible → True  (always!)
    else → litellm.supports_function_calling(model_string); exception → False
```

**E. Escalation:** scan completes in [0.40, 0.75) risk band → `escalate_scan`
reuses the **explanation** task → strict-JSON classification → only a confident
"defacement" (≥0.6) may upgrade `changed → flagged`. Never downgrades.

---

## 3. Deep Dive: the AI Provider Mechanism

### 3.1 How it decides a model "supports tool calling" — three authorities that disagree

This is the heart of your question, and it is genuinely flawed:

| # | Authority | Used at | Covers |
|---|---|---|---|
| 1 | models.dev `tool_call` flag | assignment gate (`ai_config.py:245-246`) | catalog providers only |
| 2 | live Ollama `/api/show` probe | assignment gate (`ai_config.py:234-242`) | ollama only, at save time only |
| 3 | `litellm.supports_function_calling()` static registry | runtime engine flag (`llm.py:247-252`) | catalog providers only |

**Flaws found:**

- 🔴 **P0 — Gate and runtime check use different registries and can contradict.**
  A model marked `tool_call=true` by models.dev but absent/unflagged in litellm's
  static registry passes the Settings gate, then `_supports_tools` returns **False**
  at runtime and the engine permanently refuses to chat (`engine.py:254-263`) with a
  misleading "assign a tool-capable model" message. Conversely a litellm-registry
  positive with a stale models.dev entry works but was nearly blocked at the gate.
  Two sources of truth must be reconciled into one (see §8 recommendation).

- 🟠 **P1 — Runtime flag blindly trusts Ollama/openai_compatible.** `_supports_tools`
  returns unconditional `True` for these types (`llm.py:247-248`). For Ollama, the
  `/api/show` probe result is consulted **only once, at assignment time**, and even a
  probe *failure* yields `None` → allowed (`ai_config.py:239-242`). Swap the local
  model afterwards (`ollama pull qwen` over the same tag, non-tool variant) and the
  agent keeps declaring tools to a model that cannot use them → every turn ends in
  `LLMUnavailable` noise or hallucinated tool calls. There is no re-validation.

- 🟠 **P1 — The agent-chat fallback model bypasses the tool gate completely.**
  `put_assignment` checks capability only for the primary provider/model
  (`settings.py:822-828`). Assign primary = tool-capable, fallback = any text-only
  model → accepted. When the primary fails over mid-conversation, the engine still
  sends `tools` to a model without function calling → guaranteed failure surfaced to
  the user as "assistant unavailable".

- 🟡 **P2 — `openai_compatible` is trusted blind by design** (`ai_config.py:243-244`).
  Understandable (nothing to query generically), but combined with the always-True
  runtime flag there is **zero** verification anywhere for the provider type most
  likely to actually lack tool support (LM Studio/vLLM text models). A cheap probe
  exists: `validate_provider_call` could optionally send a trivial tool schema and
  see if the response round-trips.

- 🟡 **P2 — Capability flags go stale silently.** Catalog refreshes every 12 h
  (`beat_tasks.py:442-447`) replace the tables wholesale (`upsert_catalog`,
  `ai_catalog.py:161-206`). If models.dev corrects a model's `tool_call` flag after
  you assigned it, nothing re-evaluates existing assignments; conversely a deleted
  catalog entry leaves assignments pointing at a now-unknown model with no warning
  surface (no "orphaned assignment" check anywhere).

- 🟡 **P2 — `validate_provider_call` never tests tools** (`llm.py:375-390`). A
  provider/model can show a green validation dot while being useless for agent chat.
  Validation should accept a `mode: text|tools` parameter.

### 3.2 Provider-type coverage gaps (verified against litellm's real requirements)

- 🔴 **P0 — Azure is mis-wired end-to-end.** `PROVIDER_LITELLM_PREFIX` maps
  `azure → azure` (`ai_catalog.py:52`), producing `azure/<model_id>`. But litellm's
  Azure route requires `api_base`, **`api_version`**, and typically a deployment name
  distinct from the model id. The schema has only `base_url` + free-text `model_id`;
  there is no `api_version` field anywhere in models/schemas/UI. Any Azure attempt
  fails at call time. Either implement it properly or remove `azure` from the picker.

- 🔴 **P0 — Amazon Bedrock and Google Vertex are listed but unconfigurable.** Both
  need cloud credential tuples (AWS access/secret/region; Vertex project +
  service-account JSON), not an `api_key` string. The UI collects a single key list;
  `litellm_params` only ever sets `api_key`/`api_base` (`llm.py:144-160`). These two
  catalog providers will never authenticate. Options: hide them, or add per-provider
  extra-credentials JSON (encrypted like keys).

- 🟡 **P2 — `google-vertex-anthropic` maps to `vertex_ai` prefix** — Anthropic-on-Vertex
  models need different routing in litellm (`vertex_ai/<claude-model>` works only
  with the right region/creds config). Same class of problem as Bedrock.

- 🟡 **P2 — `rpm=8` hardcoded for every key on every provider** (`llm.py:86`).
  Groq/OpenAI tolerate orders of magnitude more; a local llama.cpp box far less. One
  slow provider throttles itself artificially; one weak local daemon gets hammered
  into 429s. Make rpm a per-provider column with sane defaults per type.

### 3.3 Routing, caching, retry behavior

- ✅ Good: deployment-per-key rotation reproduces the old pool; LRU cache keyed on a
  config-generation signature preserves litellm cooldown state across requests;
  double-check insert prevents duplicate routers (`llm.py:344-358`).
- 🟠 **P1 — First-failure cooldown + single-key provider = hard outage window.**
  `allowed_fails=0`, `cooldown_time=60`, `num_retries=2` (`llm.py:89-91`): a single
  transient blip cools the only deployment for 60 s; with no fallback configured the
  feature is simply down for that minute, and the retry storm pattern repeats.
  Consider `allowed_fails=2` for single-deployment routers, or jittered cooldown.
- 🟡 **P2 — `clear_router_cache()` contradicts its own docstring**: comment says
  "Reassigning clears atomically", code does in-place `.clear()` under no lock
  (`llm.py:362-369`) while async request handlers run concurrently with
  `resolve_task`. Benign in CPython today, but it is a documented-behavior mismatch
  and a latent race; route it through `_router_cache_lock`.
- 🟡 **P2 — Timeout fixed at 30 s** (`llm.py:82`): reasoning models (o-series, R1,
  thinking-mode Gemini) routinely exceed 30 s for classification/explanations →
  spurious `LLMUnavailable`. Not configurable per provider/task.
- 🟡 **P2 — `simple-shuffle` strategy ignores the rpm metadata** it carefully sets;
  `latency-based-routing` would use cooldown+rpm properly.
- 🔵 **P3 — No token streaming anywhere.** Completions are monolithic; SSE events
  are coarse (`tool` chips + one final `done`). Long turns show only "Thinking…" for
  up to 30 s+. `router.astream_completion` + incremental `text` events (the frontend
  already lists `"text"` in `AgentStreamEvent`, `api.ts:808` — dead enum member
  today!) would transform perceived latency.

### 3.4 Secrets & credentials

- ✅ Fernet-at-rest, hint-only responses, `keys_unreadable` surfacing for rotated-key
  installs (`ai_config.py:73-100`), scrubbing of provider auth errors before logging
  (`llm.py:65-79`).
- 🟡 **P2 — No key-rotation story**: single Fernet key derived from one env string
  (`crypto.py:31-34`); no re-encrypt tooling; rotation = mass `DecryptionError`
  degradation with manual re-save of every provider/channel/token.
- 🟡 **P2 — Secret scrubbing regex `[A-Za-z0-9_\-]{32,}`** also redacts UUID-hex and
  base64 content inside legitimate error payloads — safe direction, noisy logs.
- 🟡 **P2 — `MAX_KEYS_PER_PROVIDER = 10` declared in `ai_config.py:59` "kept in sync
  with the frontend" but enforced nowhere** — neither backend schema nor UI enforces
  the cap. Comment-synced constants are a drift bug waiting to happen.

### 3.5 Catalog pipeline

- ✅ Live → keep-existing → snapshot fallback chain never blocks startup; snapshot is
  a static seed, never rewritten at runtime (avoids dirty git trees).
- 🟡 **P2 — Full table delete+reinsert twice daily** (`upsert_catalog`): brief windows
  where concurrent readers see empty tables (no transaction wrapping both deletes and
  inserts atomically is *not* guaranteed visible-safe under default isolation —
  readers on the old connection can observe the post-delete/pre-insert state).
  Wrap in one transaction or diff-upsert.
- 🔵 **P3 — Catalog data is underused**: cost/context/reasoning fields are stored and
  returned by the API but the frontend never renders them (see §6).

---

## 4. Deep Dive: the Agent Engine

### 4.1 Correctness findings

- 🟠 **P1 — No per-conversation concurrency guard.** Two simultaneous `send_message`
  calls on one conversation (double-submit, two tabs, web+Telegram same account)
  both load the window, both drive turns, interleave persisted rows, and corrupt the
  rolling summary input. The confirm path got atomic claiming; the *turn* path did
  not. Fix: Postgres advisory lock on `conversation.id`, or a per-conversation
  in-process mutex + 409.
- 🟡 **P2 — Client abort leaves half-executed tool chains.** The SSE generator
  commits as it goes (good), but a disconnect mid-loop stops between tool executions:
  transcript shows tool rows whose results the model never saw, and the turn just…
  ends with no assistant wrap-up until the next user message. Acceptable trade-off,
  but worth a "turn interrupted" sentinel row.
- 🟡 **P2 — Confirm-resume gap.** After `resolve_pending(confirm=True)` executes the
  frozen args, **the outcome is never fed back to the model** — the executed result
  is returned to the HTTP caller only. The web UI refetches the transcript (which
  shows nothing about the execution) and the Telegram bot prints a canned "Action
  confirmed and carried out." (`telegram_bot.py:594-597`). The assistant cannot
  answer "did it work?" without the user re-asking. Enhancement: append the execution
  result as a system/tool note and optionally resume the loop for one iteration.
- 🟡 **P2 — Cross-turn injection containment resets.** `untrusted_in_turn` is scoped
  to one turn (`engine.py:280`); prior-turn assistant prose quoting hostile content
  *is* replayed in later windows (`context.build_contents` replays user/assistant
  rows), where tier-1 auto-execution is armed again. A jailbreak seeded via an
  incident explanation in turn N can influence turn N+1. Mitigation: taint flag on
  the conversation row (sticky for the session), not per-turn.
- 🟡 **P2 — Loop-exhaustion UX.** At `MAX_ITERATIONS=5` the canned message replaces
  whatever partial progress happened; parallel multi-tool-call iterations burn the
  budget fast. Consider making the cap configurable and emitting a `tool` event when
  the cap trips so the UI can explain.
- 🔵 **P3 — Tool arg parsing is try/except-shaped, not schema-shaped.**
  e.g. `_list_scans`: `int(args.get("limit", 5))` raises on `"abc"` → generic
  "That action failed unexpectedly" instead of a corrective message the model could
  learn from. Per-tool Pydantic arg models would give precise, model-actionable
  errors and self-document schemas.
- 🔵 **P3 — `_resolve_site` ILIKE wildcard leakage:** `%ref%` lets a model-supplied
  `%`/`_` act as wildcards (matching semantics surprise, not injection). Escape
  `%`/`_` in the fragment.
- 🔵 **P3 — Rolling summary pays an extra LLM call on *every* turn once the
  transcript exceeds 18 rows** (`maybe_summarize` runs each completed turn). Debounce
  (e.g., regenerate at most every N messages or M minutes).

### 4.2 Security posture (strong overall — verified, not assumed)

- ✅ RBAC is enforced in the dispatcher (`can_call`) *and* declarations are filtered
  per role (`tools_for_role`) — the model never sees tools above the user
  (`tools.py:169-178`).
- ✅ Confirmation guard freezes args verbatim; ownership/RBAC/expiry re-checked at
  confirm; atomic conditional-UPDATE claim defeats double-click races
  (`guard.py:116-151`); expired-card settlement is also conditional.
- ✅ Tier mapping is sensible; `delete_site` analyst+confirmation matches REST
  (`sites.py:278 AnalystUser`); `list_remediation_hooks` deliberately admin-only.
- ✅ Injection containment is layered: fenced untrusted payloads with forged-marker
  defanging (`tools.py:83-104`), system-instruction teaching, plus code-enforced
  auto-exec suspension (defense does not rest on prompt compliance).
- ✅ Result bounding happens on data before serialization (`_bound_result`), so the
  JSON fed to the model is always valid and bounded (4000-char backstop).
- 🟡 **P2 — `run_scan_now` (tier 1) auto-executes** and triggers outbound requests to
  a third-party site. An injected instruction that survives fencing could still get
  a viewer…no—analyst to repeatedly scan an attacker-chosen target (scan-amplification
  harassment). Cheap fix: require confirmation for scan-now too, or add per-conversation
  rate limiting on tier-1 executions.
- 🟡 **P2 — Agent endpoints have no rate limit** (`routers/agent.py` uses no
  `enforce_user_rate_limit`): any authenticated viewer can drive unlimited paid LLM
  turns (bounded only by the 50-conversation cap and 4000-char message cap). Add
  per-user turn rate limiting like the validate/pull endpoints have.
- 🔵 **P3 — SSE lacks heartbeat comments** during long silent LLM calls; aggressive
  proxies may kill idle-looking streams despite `X-Accel-Buffering: no`.
- 🔵 **P3 — Frontend frame parser splits only on `"\n\n"`** (`api.ts:886`); CRLF
  proxies would break parsing. Tolerate `\r?\n\r?\n`.

---

## 5. Escalation, Explain, Context Subsystems

- ✅ Fail-safe direction is right: LLM can only raise `changed→flagged`, never
  suppress; every outcome recorded in evidence; unparseable replies handled.
- 🟡 **P2 — Escalation shares the `explanation` task and its rpm=8 budget.** A burst
  of ambiguous scans (mass-defacement event — precisely when it matters) competes
  with interactive explanations and the agent's rolling summaries. Give escalation
  its own task type (third `AiTaskType`) or a reserved budget.
- 🟡 **P2 — Classification relies on prompt-discipline JSON** with a regex fallback
  `\{.*?\}` (`llm.py:487`) that breaks on nested objects. Fine for the current flat
  shape; brittle if the schema evolves. Structured outputs / `response_format` where
  supported would harden it.
- 🔵 **P3 — `generate()` truncates at 4000 chars mid-word** (`llm.py:210`); harmless
  today (summaries/explanations), ugly if reused elsewhere.
- 🔵 **P3 — Summary primer masquerades as a fake user/assistant exchange**
  (`context.py:122-125`); some strict providers penalize fabricated history, and
  "Understood." wastes tokens. A single prefixed system-style note would be cleaner
  where supported.

---

## 6. Frontend Analysis

### `pages/assistant.tsx`
- ✅ Solid streaming lifecycle: abort on unmount, optimistic user bubble with server
  reconciliation on error, retry dedupe, near-bottom autoscroll, focus-refetch gated
  on `!streaming`, optimistic pending-action cache write (STR-4).
- 🔴 **P2/P1 boundary — Conversation dead-end at the 50 cap.** Listing shows newest
  50 (`agent.py:63-73`) and creation 409s at ≥50 (`agent.py:87-96`): a user at the
  cap can neither reach older conversations (unlisted) nor create new ones without
  deleting blind. Add pagination or oldest-delete affordance.
- 🟡 No stop-generation button — `abortRef` exists but only fires on unmount; a
  stuck 30 s turn cannot be cancelled from the UI.
- 🟡 Tool chip resolution matches "any start-state chip with the same tool name"
  (`assistant.tsx:443`) — two parallel calls of the same tool resolve the wrong chip.
  Key chips by tool_call id (backend has it and doesn't send it).
- 🔵 Transcript filter hides assistant tool-call rows entirely (`assistant.tsx:354-357`)
  — reasonable, but means users can't audit what the model asked to do after reload.
  A collapsible "activity" disclosure would preserve auditability.

### `components/ai-settings-card.tsx` — the biggest enhancement surface
- 🔴 **Model selection is paste-only.** The backend exposes a rich catalog models
  endpoint with `tools_only` filtering, pricing, context windows
  (`settings.py:623-650`, `api.ts:listCatalogModels`) — **and the UI never calls it.**
  Users hand-type `gemini-2.0-flash`-style ids with no validation until a failed
  validate/turn. Build the searchable model dropdown: capability badges (tools /
  reasoning), price display, context size — all data already sits in the DB.
- 🟠 **No edit / enable-disable / validate controls.** `PATCH /providers/{id}` and
  `POST /providers/{id}/validate` exist and are wired in `api.ts` but unused by the
  card: changing a key requires delete+recreate; the validation status dot renders
  (`validationDot`) but there is no button that triggers validation. An operator
  cannot diagnose a failing provider from the UI.
- 🟠 **Fallback assignment not exposed.** Backend fully supports cross-provider
  fallbacks; the dialog/rows offer no fallback pickers — the redundancy feature is
  invisible.
- 🟡 `isLocalOrKeyless` heuristic treats *any* `http://` catalog api_base as keyless
  local (`ai-settings-card.tsx:159`) — loose; a hosted http endpoint would allow
  empty keys (harmless-ish but wrong messaging).
- 🟡 Auto-assign checkboxes assign one model to both tasks; a non-tool model fails
  `agent_chat` with a toast (handled well via `assignModelToTasks`), but for
  `openai_compatible` it "succeeds" regardless of true capability (mirrors §3.1).
- 🔵 Provider rows don't show which tasks/models currently point at them, nor warn
  that deletion unassigns tasks (CASCADE) leaving features silently unconfigured.

---

## 7. Consolidated Issue Register

| ID | Sev | Area | Issue | Where |
|---|---|---|---|---|
| F-1 | 🔴 | Providers | Tool-gate (models.dev) vs runtime flag (litellm registry) can disagree → gated-in model refused at runtime | `ai_config.py:245` vs `llm.py:247-252` |
| F-2 | 🔴 | Providers | Azure: no api_version/deployment handling → unusable | `ai_catalog.py:52`, `llm.py:144` |
| F-3 | 🔴 | Providers | Bedrock/Vertex listed but impossible to authenticate via key-list UI | `llm.py:144-160` |
| F-4 | 🟠 | Providers | agent_chat **fallback** skips the tool gate | `settings.py:822` |
| F-5 | 🟠 | Providers | Runtime `supports_tools=True` unconditional for ollama/openai_compatible; Ollama probe never re-run | `llm.py:247` |
| F-6 | 🟠 | Agent | No per-conversation turn concurrency guard | `engine.run_turn` |
| F-7 | 🟠 | Agent | Agent endpoints unrate-limited → paid-LLM abuse by any viewer | `routers/agent.py` |
| F-8 | 🟠 | Providers | first-fail 60s cooldown on sole deployment = outage windows | `llm.py:89-91` |
| F-9 | 🟡 | Providers | rpm=8 global constant | `llm.py:86` |
| F-10 | 🟡 | Providers | 30s timeout kills reasoning models; unconfigurable | `llm.py:82` |
| F-11 | 🟡 | Providers | MAX_KEYS_PER_PROVIDER enforced nowhere | `ai_config.py:59` |
| F-12 | 🟡 | Providers | clear_router_cache unlocked + docstring mismatch | `llm.py:362` |
| F-13 | 🟡 | Providers | Catalog refresh delete+insert visibility window | `ai_catalog.py:171` |
| F-14 | 🟡 | Agent | Confirm result never fed back to model | `guard.resolve_pending` |
| F-15 | 🟡 | Agent | Injection taint resets per turn while quoted hostile prose persists across turns | `engine.py:280` |
| F-16 | 🟡 | Agent | run_scan_now auto-exec enables scan amplification via injection | `tools.py:809-818` |
| F-17 | 🟡 | Escalation | Shares explanation task/budget; storm contention | `worker/llm_escalation.py:60` |
| F-18 | 🟡 | Frontend | Conversation dead-end at 50-cap | `agent.py:63,87` |
| F-19 | 🟡 | Frontend | No edit/disable/validate/fallback UI; model picker paste-only | `ai-settings-card.tsx` |
| F-20 | 🔵 | Engine | Per-tool arg validation absent; wildcard leak in site resolve; summary regen每turn cost | §4.1 |
| F-21 | 🔵 | UX | No token streaming; no stop button; no SSE heartbeat | §3.3/§6 |

---

## 8. Recommendations & Framework/Library Opportunities

### Priority fixes (smallest effort → biggest payoff)
1. **Unify tool-capability truth**: store a resolved `supports_tools` boolean on
   `AiTaskAssignment` at assignment time (catalog ∨ probe ∨ optional live tool-probe),
   and make the engine read *that* — deleting the divergent
   `litellm.supports_function_calling` runtime path (fixes F-1/F-5/F-4 in one move;
   also gate the fallback model).
2. **Hide/repair Azure, Bedrock, Vertex** in the catalog picker (F-2/F-3): either a
   proper extra-credentials field (encrypted JSON blob per provider) or filter those
   ids out of `/catalog/providers` until supported.
3. **Rate-limit agent endpoints** using the existing `enforce_user_rate_limit`
   primitive (F-7).
4. **Per-conversation turn lock** — Postgres advisory lock mirrors the codebase's
   existing CAS style (F-6).
5. **Expose Validate/Edit/Fallback/Model-picker in the settings card** — all backend
   APIs already exist; pure frontend work (F-19).

### Library opportunities (evaluate, don't blanket-adopt)
- **Keep the hand-rolled agent loop.** LangGraph / OpenAI Agents SDK / CrewAI would
  add heavy abstraction over what is a ~400-line, security-audited loop with custom
  confirmation semantics they don't natively express. Not worth it here.
- **Pydantic AI** is the closest philosophical match (typed tools, pydantic args);
  worth a spike if tool-count grows, but migration must preserve the tier/guard
  machinery.
- **Instructor** (or litellm `response_format`/structured outputs) for the
  classification JSON — removes regex parsing (§5).
- **LiteLLM callbacks** (`litellm.success_callback`) for usage/cost capture → a
  spend ledger table + dashboard widget; pairs naturally with the already-stored
  models.dev pricing (currently dead weight).
- **Langfuse (self-hosted)** or **OpenTelemetry GenAI conventions** for tracing
  turns/tools/tokens — high value for an ops product; keep opt-in.
- **MCP (Model Context Protocol)** server exposure for the tool registry later —
  the `Tool` dataclass is already schema-first; an MCP facade is cheap once stable.

### Product-grade enhancements
- Token streaming (`astream_completion`) + `text` delta events (enum member already
  reserved) + stop button.
- Sticky per-conversation injection taint (F-15).
- Third `AiTaskType.escalation` with its own assignment (F-17).
- Orphaned-assignment detector after catalog sync: warn when assigned models vanish
  from the catalog.
- Conversation pagination/search; tool_call-id-keyed activity chips; collapsible
  tool-activity transcript.

### Test coverage note
Good existing coverage to protect while refactoring: `tests/test_agent.py`,
`test_agent_prompt_injection.py`, `test_phase25_agent_subsystem.py`,
`test_ai_catalog.py`, `test_ai_migration.py`, `test_llm_keypool.py`,
`test_phase37_scheduling_agent_remediation.py`. Run with
`uv run pytest backend/tests/test_agent.py …` from the backend venv.

---

## 9. Verified-Strengths Checklist (do not regress)

- Single call-site; secrets never leave backend (hint-only); error scrubbing.
- Silent-degradation contract everywhere (`LLMUnavailable` / `ExplainError` /
  `ToolError`); AI can never block or crash a scan.
- Code-enforced RBAC + confirmation; atomic pending-action claims; TTL janitor.
- Structural prompt-injection defense (fencing + defanged markers + dispatcher
  suspension) independent of model compliance.
- Same service layer behind REST, agent tools, Telegram — no permission widening
  (spot-checked `delete_site` parity).
- Escalation monotonicity (raise-only) with evidence recording.
- Catalog offline resilience (snapshot seed; DB retention between syncs).
