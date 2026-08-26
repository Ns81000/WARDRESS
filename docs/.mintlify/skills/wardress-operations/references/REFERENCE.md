# Wardress documentation map

This index mirrors the project's `llms.txt`. Use it to locate deeper, human-written
documentation when a task needs more detail than this skill's workflows provide.
All entries are served as Markdown from the documentation site.

Base: <https://wardress.mintlify.site>

## Get Started

- [Introduction](https://wardress.mintlify.site/introduction): Self-hosted website defacement detection and automated response orchestration.
- [Installation](https://wardress.mintlify.site/installation): Deploy Wardress in minutes using the automated installation scripts.

## Platform Guide

- [Usage & Dashboard](https://wardress.mintlify.site/usage): Manage monitored sites, handle alerts, and orchestrate automated remediations.
- [Detection Pipeline](https://wardress.mintlify.site/detection-layers): The 9 specialized analysis layers that power the fused risk model.

### Detection layers (deep dive)

- [Layer 1: Content Hash](https://wardress.mintlify.site/layers/1-content-hash): Foundational byte-level integrity check that gates the rest of the pipeline.
- [Layer 2: DOM Structure](https://wardress.mintlify.site/layers/2-dom-structure): Structural tampering, script injections, iframe hijacks, and hidden elements.
- [Layer 3: Link Audit](https://wardress.mintlify.site/layers/3-link-audit): Hijacked traffic and unauthorized external resources via reference-set diffing.
- [Layer 4: Visual Diff](https://wardress.mintlify.site/layers/4-visual-diff): Computer-vision analysis combining structural similarity with perceptual hashing.
- [Layer 5: Signatures](https://wardress.mintlify.site/layers/5-signatures): Defacement phrases, profanity bursts, and Unicode script flips in new visible text.
- [Layer 6: Security Metadata](https://wardress.mintlify.site/layers/6-security-metadata): TLS certificates, security headers, and robots.txt — independent of the HTML body.
- [Layer 7: Cloaking](https://wardress.mintlify.site/layers/7-cloaking): SEO-spam and targeted evasion via User-Agent rotation and intra-scan comparison.
- [Layer 8: Semantics](https://wardress.mintlify.site/layers/8-semantics): Local NLP — aggression lexicon, topic shift, and MiniLM semantic drift.
- [Layer 9: Risk Fusion](https://wardress.mintlify.site/layers/9-risk-fusion): The logistic-regression classifier that fuses eight sub-scores into one risk score.

## Frontend SPA

- [Frontend Architecture](https://wardress.mintlify.site/frontend/architecture): Technologies, routing, state model, and security controls of the SPA.
- [Scan Detail UI](https://wardress.mintlify.site/frontend/scan-detail): The interactive forensic workbench for analyzing why a scan was flagged.
- [Reusable Components](https://wardress.mintlify.site/frontend/components): Core UI components that drive the dashboard.

## Administration

- [Configuration Reference](https://wardress.mintlify.site/configuration): Environment variables and Role-Based Access Control.
- [User Management & RBAC](https://wardress.mintlify.site/user-management): Strict Role-Based Access Control and session security.
- [API Reference](https://wardress.mintlify.site/api-reference): The full REST endpoint map.
- [Remediation Hooks](https://wardress.mintlify.site/remediation-hooks): Automated incident response when a site is flagged.
- [AI Agent](https://wardress.mintlify.site/agent): The conversational AI interface inside Wardress.
- [Agent Skill](https://wardress.mintlify.site/agent-skill): This skill, documented for human readers.
- [Audit Logs](https://wardress.mintlify.site/audit-logs): The immutable ledger of system actions.
- [Security & Development](https://wardress.mintlify.site/security-and-dev): Security mechanisms and local development setup.
