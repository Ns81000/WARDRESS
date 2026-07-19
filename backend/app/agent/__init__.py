"""Agent package (§ agent): the conversational assistant core shared by
the web dashboard chat and the Telegram bot.

Layout:
- tools.py   — tool registry: Gemini function declarations + executors
- guard.py   — action tiers + the confirm-before-execute pending store
- context.py — token-efficient conversation context building
- engine.py  — the Gemini function-calling turn loop (event stream)

Design rules (locked in Build/PLAN-conversational-agent.md):
- RBAC is enforced in code at dispatch, never delegated to the model; a
  user's tool list is filtered by role *before* declaration.
- Tier >= 2 tools are intercepted and frozen as pending actions; the model
  is not in the loop between propose and execute.
- Tool results are compact JSON (capped lists, 8-char id prefixes, no raw
  HTML/evidence) — token efficiency and prompt-injection containment.
- Model: gemini-flash-latest through the llm.KeyPool rotation pool.
"""
