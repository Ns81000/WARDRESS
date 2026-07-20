import type { FlowSpec } from './types';

// ============================================================
// Adaptive Cadence — how Wardress decides when to scan next.
//
// Sourced from the detection-layers / fusion documentation:
//   - Celery Beat ticks every 60s and dispatches due scans.
//   - Material-change threshold: 0.15.
//   - Tighten on change: next interval = base ÷ 4.
//   - Relax on clean scans: interval ×1.5 each clean scan, up to base.
//   - Clamp: every interval bounded to [5 minutes, 24 hours].
//   - Adaptive state lives in the DB — a restart loses nothing.
//
// This second flow exists to prove the engine is content-driven:
// it is pure data, no bespoke components, and renders through the
// exact same FlowCanvas as the pipeline.
// ============================================================

const MID_Y = 200;

export const cadenceFlow: FlowSpec = {
  id: 'cadence',
  name: 'Adaptive Cadence',
  blurb: 'The scan interval breathes — tightening the moment something changes, relaxing as the page stays calm.',
  hasGate: false,
  steps: [
    'Celery Beat ticks every 60 seconds, dispatching any site whose next scan is due.',
    'The scan runs and produces a fused risk score.',
    'Below 0.15 the page is calm; at or above 0.15 it is a material change.',
    'On a material change, the next interval tightens to a quarter of the base.',
    'Each clean scan afterwards relaxes the interval back by half again, up to the base.',
    'Every interval is clamped to a sane floor and ceiling before it is stored.',
  ],

  nodes: [
    {
      id: 'beat',
      kind: 'io',
      title: 'Celery Beat',
      tagline: 'ticks every 60s',
      accent: 'neutral',
      gateRole: 'none',
      systemKey: 'beat',
      position: { x: 0, y: MID_Y },
      step: 0,
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
      title: 'Scan runs',
      tagline: '9-layer pipeline → fused score',
      accent: 'blue',
      gateRole: 'none',
      position: { x: 320, y: MID_Y },
      step: 1,
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
      kind: 'layer',
      title: 'Material change?',
      tagline: 'threshold 0.15',
      accent: 'orange',
      gateRole: 'none',
      systemKey: 'MATERIAL_CHANGE_RISK',
      position: { x: 640, y: MID_Y },
      step: 2,
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
      title: 'Tighten',
      tagline: 'next = base ÷ 4',
      accent: 'red',
      gateRole: 'none',
      position: { x: 980, y: 60 },
      step: 3,
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
      title: 'Relax',
      tagline: 'interval ×1.5 per clean scan',
      accent: 'green',
      gateRole: 'none',
      position: { x: 980, y: 340 },
      step: 4,
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
      title: 'Clamp',
      tagline: '[5 min, 24 h]',
      accent: 'blue',
      gateRole: 'none',
      position: { x: 1320, y: MID_Y },
      step: 5,
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
      title: 'Next scan',
      tagline: 'persisted',
      accent: 'neutral',
      gateRole: 'none',
      systemKey: 'next_scan_at',
      position: { x: 1660, y: MID_Y },
      step: 5,
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
    { id: 'c-beat-scan', source: 'beat', target: 'scan', step: 0, accent: 'neutral' },
    { id: 'c-scan-dec', source: 'scan', target: 'decide', step: 1, accent: 'blue' },
    { id: 'c-dec-tight', source: 'decide', target: 'tighten', step: 2, accent: 'red' },
    { id: 'c-dec-relax', source: 'decide', target: 'relax', step: 2, accent: 'green' },
    { id: 'c-tight-clamp', source: 'tighten', target: 'clamp', step: 3, accent: 'red' },
    { id: 'c-relax-clamp', source: 'relax', target: 'clamp', step: 4, accent: 'green' },
    { id: 'c-clamp-store', source: 'clamp', target: 'store', step: 5, accent: 'blue' },
    // the loop back — cadence is continuous
    { id: 'c-store-beat', source: 'store', target: 'beat', step: 5, accent: 'neutral' },
  ],
};
