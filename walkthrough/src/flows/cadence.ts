import type { FlowSpec } from './types';

// ============================================================
// Adaptive Cadence — how Wardress decides when to scan next.
//
// Sourced from the detection-layers / fusion documentation:
//   - Celery Beat ticks every 60s and dispatches due scans.
//   - Material-change threshold: 0.15 (the decision branch).
//   - Tighten on change: next interval = base ÷ 4.
//   - Relax on clean scans: interval ×1.5 each clean scan, up to base.
//   - Clamp: every interval bounded to [5 minutes, 24 hours].
//   - Adaptive state lives in the DB — a restart loses nothing.
//
// A second flow that proves the engine is content-driven: pure data,
// same Mermaid renderer, no bespoke code.
// ============================================================

export const cadenceFlow: FlowSpec = {
  id: 'cadence',
  name: 'Adaptive Cadence',
  blurb: 'The scan interval breathes — tightening the moment something changes, relaxing as the page stays calm.',
  direction: 'LR',
  hasGate: false,

  nodes: [
    {
      id: 'beat',
      kind: 'input',
      label: 'Celery Beat · 60s',
      accent: 'neutral',
      gateRole: 'none',
      systemKey: 'beat',
      detail: {
        plain: 'The heartbeat that decides, once a minute, which sites are due for a scan.',
        blocks: [
          {
            label: 'How it works',
            body: 'A Celery Beat scheduler wakes every 60 seconds and asks the database which monitored sites have reached their next-scan time. Each due site is dispatched to a worker. Beat itself holds no state — the schedule lives in the database.',
          },
          {
            label: 'Why the DB holds the schedule',
            body: 'Because next-scan times are persisted, a restart of the scheduler or workers loses nothing. The cadence picks up exactly where it left off.',
          },
        ],
      },
    },
    {
      id: 'scan',
      kind: 'stage',
      label: 'Scan runs',
      accent: 'blue',
      gateRole: 'none',
      detail: {
        plain: 'The full detection pipeline runs and hands back one calibrated risk score.',
        math: 'fused_risk ∈ [0.0, 1.0]',
        blocks: [
          {
            label: 'How it works',
            body: 'The worker runs the nine-layer pipeline against the baseline and produces a single fused risk score between 0.0 and 1.0. That number is what the cadence logic reacts to.',
          },
        ],
      },
    },
    {
      id: 'decide',
      kind: 'decision',
      label: 'risk ≥ 0.15?',
      accent: 'orange',
      gateRole: 'none',
      systemKey: 'MATERIAL_CHANGE_RISK',
      detail: {
        plain: 'A single dividing line: is this ordinary noise, or something worth reacting to?',
        math: 'fused_risk ≥ 0.15',
        blocks: [
          {
            label: 'How it works',
            body: 'The fused score is compared against the material-change threshold of 0.15. Below it, the page is treated as calm and the cadence relaxes. At or above it, Wardress treats the scan as a material change and tightens the cadence.',
          },
          {
            label: 'Why 0.15',
            body: 'It sits deliberately below any sane alerting threshold, yet above the noise of ordinary dynamic content — rotating banners, A/B tests, timestamps. Enough to react early without chasing every flicker.',
          },
        ],
      },
    },
    {
      id: 'tighten',
      kind: 'layer',
      label: 'Tighten · base ÷ 4',
      accent: 'red',
      gateRole: 'none',
      detail: {
        plain: 'Something moved — so look again much sooner.',
        math: 'interval = base ÷ 4',
        blocks: [
          {
            label: 'How it works',
            body: 'When a scan crosses the material-change threshold, the next interval is set to a quarter of the base interval. If a site is normally scanned every 24 hours, the next check lands in roughly 6 — Wardress leans in the moment the page starts changing.',
          },
        ],
      },
    },
    {
      id: 'relax',
      kind: 'layer',
      label: 'Relax · ×1.5',
      accent: 'green',
      gateRole: 'none',
      detail: {
        plain: 'Calm restored — so gradually ease back off, without snapping straight to normal.',
        math: 'interval = min(interval × 1.5, base)',
        blocks: [
          {
            label: 'How it works',
            body: 'After a tightening, each subsequent clean scan multiplies the interval by 1.5, easing back toward the base interval rather than jumping straight to it. A page that was recently touched stays under closer watch until it has proven calm for a while.',
          },
        ],
      },
    },
    {
      id: 'clamp',
      kind: 'fusion',
      label: 'Clamp [5m, 24h]',
      accent: 'purple',
      gateRole: 'none',
      detail: {
        plain: 'A guardrail so the interval can never get absurdly short or dangerously long.',
        math: 'clamp(interval, 5 min, 24 h)',
        blocks: [
          {
            label: 'How it works',
            body: 'Before the next-scan time is written back to the database, the interval is clamped to a floor of 5 minutes and a ceiling of 24 hours. Even a very active page is never hammered more than once every 5 minutes, and even a dormant one is always checked at least daily.',
          },
        ],
      },
    },
    {
      id: 'store',
      kind: 'score',
      label: 'Next scan',
      accent: 'neutral',
      gateRole: 'none',
      systemKey: 'next_scan_at',
      detail: {
        plain: 'The chosen moment for the next look, written down so nothing forgets it.',
        blocks: [
          {
            label: 'How it works',
            body: 'The clamped next-scan time is stored on the site record. On the next 60-second tick, Beat will find it when it is due and the loop begins again — a cadence that continuously adapts to how the page actually behaves.',
          },
        ],
      },
    },
  ],

  edges: [
    { source: 'beat', target: 'scan', accent: 'neutral' },
    { source: 'scan', target: 'decide', accent: 'blue' },
    { source: 'decide', target: 'tighten', label: 'yes · changed', accent: 'red' },
    { source: 'decide', target: 'relax', label: 'no · clean', accent: 'green' },
    { source: 'tighten', target: 'clamp', accent: 'red' },
    { source: 'relax', target: 'clamp', accent: 'green' },
    { source: 'clamp', target: 'store', accent: 'purple' },
    { source: 'store', target: 'beat', label: 'loops', accent: 'neutral' },
  ],
};
