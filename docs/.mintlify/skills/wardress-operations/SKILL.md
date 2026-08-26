---
name: wardress-operations
description: Operate Wardress, a self-hosted website defacement detection platform, over its REST API. Check system health, list monitored sites and alerts, trigger manual scans, acknowledge alerts, triage flagged scans by interpreting 9-layer evidence and fused risk scores, manage suppression rules, export incident reports, and confirm or dismiss pending remediation webhooks. Use when the user asks to monitor, triage, or respond to website defacement incidents through Wardress, or mentions Wardress, defacement detection, site integrity monitoring, or flagged scans.
license: MIT
compatibility: Requires network access to a running Wardress instance (default http://localhost:8321) and an API key (wk_...) generated in Settings → API Keys.
metadata:
  author: Ns81000
  version: "1.0"
---

# Wardress operations

Wardress is an API-first, self-hosted security tool that detects website
defacements. It freezes a trusted baseline of each monitored site (DOM
structure, network references, visual layout, textual semantics) and scores
every scan across nine detection layers into a single fused risk score in
`0.0–1.0`. This skill teaches you how to operate a Wardress instance on the
operator's behalf over its REST API.

Full human documentation: <https://wardress.mintlify.site>

## Base URL and authentication

- Base URL: `http://localhost:8321` unless the operator gives another host.
  Every API route is mounted under the `/api` prefix.
- Authentication is a Bearer token in the `Authorization` header:

  ```
  Authorization: Bearer wk_your_api_key_here
  ```

- API keys look like `wk_` followed by 43 URL-safe characters. The operator
  creates one in **Settings → API Keys**; the raw value is shown exactly once,
  so ask the operator for it — never guess or invent one.
- A `401` means missing/invalid credential; a `403` means the key owner's role
  is insufficient for the endpoint.

### Role model

Every credential carries one of three roles, enforced per endpoint:

| Role | Scope |
| :--- | :--- |
| admin | Everything: users, settings, notification channels, remediation hooks, audit log |
| analyst | Sites, scans, rebaselines, suppression rules, alert acks, explains, reports, remediation confirm/dismiss |
| viewer | Read-only GET surfaces |

API keys cannot manage credentials: endpoints under `/api/api-keys` and
`/api/auth/logout` reject API keys outright — they require an interactive
browser session. Never attempt credential management with an API key.

## Core workflows

### 1. Check system health

```
GET /api/health          → queue depth, worker heartbeats, throughput
GET /api/health/live     → liveness probe (unauthenticated)
```

Start here if scans seem stalled: a deep Celery queue or missing worker
heartbeat explains delayed results before any retry logic.

### 2. Review sites and their status

```
GET /api/sites           → all monitored sites with current status
GET /api/sites/{id}      → one site's configuration and state
```

Site status values include Healthy, Flagged, and Scanning. Each site carries
its own flag threshold; a scan whose fused risk score meets it raises an alert.

### 3. Triage alerts

```
GET  /api/alerts         → paged alert history
GET  /api/alerts/{id}    → single alert detail
POST /api/alerts/{id}/ack → acknowledge an alert (analyst+)
```

Acknowledge only after review — acking is a state change recorded in the audit
log. Never bulk-ack unexamined alerts.

### 4. Investigate a flagged scan

```
GET /api/sites/{id}/scans                 → scan history
GET /api/sites/{id}/scans/{scanId}        → scan detail with per-layer findings
POST /api/sites/{id}/scans/{scanId}/explain → plain-English AI summary (analyst+)
GET /api/reports/{scanId}/markdown        → Markdown incident report
GET /api/reports/{scanId}/pdf             → PDF incident report
```

When interpreting findings:

- The fused `risk_score` is a **ranking signal**, not a calibrated probability.
  Read it as "more/less evidence of defacement."
- Findings carry stable layer keys: `layer1_hash`, `layer2_dom_structure`,
  `layer3_link_audit`, `layer4_visual_diff`, `layer5_signatures`,
  `layer6_security_metadata`, `layer7_cloaking`, `layer8_semantics`,
  `layer9_fusion`.
- High-specificity signals — new external script/iframe/form-action domains
  (`layer3_link_audit`), defacement signatures (`layer5_signatures`), crawler
  cloaking (`layer7_cloaking`) — are the strongest attack evidence. Ordinary
  churn (timestamps, rotating ads) scores well below typical flag thresholds.
- A layer may report `None` with error evidence after a parser crash; the other
  eight layers still completed. Treat it as degraded data, not as "no change."

### 5. Trigger actions

```
POST /api/sites/{id}/scan-now      → run an immediate scan (analyst+)
POST /api/sites/{id}/rebaseline    → re-capture the trusted baseline (analyst+, returns 202)
```

Rebasing erases the current trusted state — confirm with the operator before
calling rebaseline, especially right after a suspected incident.

### 6. Manage suppression rules

```
GET/POST/DELETE /api/sites/{id}/suppression-rules[/{ruleId}]
```

Suppression rules are regexes that filter known-dynamic page regions out of
diffing. Add them only for genuinely dynamic content (rotating ads, session
tokens); never to silence real attack evidence.

### 7. Handle remediation executions

```
GET  /api/remediation/executions?pending_only=true → pending webhook firings
POST /api/remediation/executions/{id}/confirm      → approve firing (analyst+)
POST /api/remediation/executions/{id}/dismiss      → reject firing (analyst+)
```

Remediation hooks POST incident payloads to operator infrastructure (rollback
endpoints, maintenance-page swaps). Executions default to a manual-confirmation
queue precisely because they can take healthy sites offline. Always surface the
hook's target and action type to the operator and get explicit approval before
confirming — never auto-confirm remediations yourself.

## Operational constraints

- **Rate limits**: per-IP and per-user limits return `429` with a
  `Retry-After` header. Back off and honor the header; do not hammer retries.
- **Request size**: oversized bodies fail with `413`.
- **Idempotency of scans**: repeated `scan-now` calls queue repeated scans;
  check `/api/sites/{id}` status first when unsure whether one is already due.
- **Adaptive cadence**: after a material change (risk ≥ 0.40) the scan interval
  tightens automatically; clean runs relax it back toward the base interval.
  You do not need to schedule catch-up scans manually.
- **Artifacts**: baseline and scan screenshots/HTML live under
  `/api/artifacts/baselines/{id}` and `/api/artifacts/scans/{id}` and are
  read-only.

## Example session

```bash
# Health first
curl -H "Authorization: Bearer $WARDRESS_API_KEY" http://localhost:8321/api/health

# Which sites need attention?
curl -H "Authorization: Bearer $WARDRESS_API_KEY" http://localhost:8321/api/sites

# Pull open alerts
curl -H "Authorization: Bearer $WARDRESS_API_KEY" http://localhost:8321/api/alerts

# Deep-read the latest flagged scan, then summarize it
curl -H "Authorization: Bearer $WARDRESS_API_KEY" \
  http://localhost:8321/api/sites/<site_id>/scans/<scan_id>
curl -X POST -H "Authorization: Bearer $WARDRESS_API_KEY" \
  http://localhost:8321/api/sites/<site_id>/scans/<scan_id>/explain
```

Report findings to the operator with: overall risk score, which layers fired
and why, whether the evidence pattern matches churn vs. attack, and the
recommended next action (suppress, rebaseline, ack, or escalate).

## Further reading

For deeper detail on any capability, consult the project's documentation index
in [references/REFERENCE.md](references/REFERENCE.md). It mirrors the site's
`llms.txt` and links to the full per-layer, API, and agent guides. Load it only
when a task calls for specifics beyond the workflows above.
