import type { FlowSpec } from './types';

// ============================================================
// Detection Pipeline — the 9-layer scan, URL → fused risk score.
//
// Hover copy is technical but tight: one line on what each layer
// actually computes. Sourced from the Wardress detection-layers docs.
// ============================================================

export const pipelineFlow: FlowSpec = {
  id: 'pipeline',
  name: 'Detection Pipeline',
  blurb: 'One scan, nine independent witnesses, fused into a single calibrated risk score.',
  direction: 'LR',
  hasGate: true,

  nodes: [
    // ---- inputs & capture ----
    {
      id: 'url',
      kind: 'input',
      label: 'Monitored URL',
      accent: 'neutral',
      gateRole: 'none',
      detail: {
        tech: 'Enrolled target. Baseline (HTML, resources, masked screenshot, text embedding) frozen once; every scan diffs against it, never the previous scan.',
      },
    },
    {
      id: 'capture',
      kind: 'stage',
      label: 'Capture',
      accent: 'neutral',
      gateRole: 'none',
      systemKey: 'playwright',
      detail: {
        tech: 'Headless Chromium (Playwright) renders the page — JS executed, layout settled — emitting original HTML, UA-rotated fetches, and a masked grayscale screenshot.',
      },
    },

    // ---- layer 1 + the skip decision ----
    {
      id: 'layer1',
      kind: 'layer',
      label: 'Content Hash',
      accent: 'blue',
      gateRole: 'always',
      index: '01',
      systemKey: 'layer1_hash',
      detail: {
        tech: 'SHA-256 over conservatively-normalized ORIGINAL HTML (never suppressed). Binary: 0.0 match / 1.0 differ. Drives the skip gate.',
        math: 'SHA-256(normalize(html)) → 0.0 / 1.0',
      },
    },
    {
      id: 'gate',
      kind: 'decision',
      label: 'Bytes changed?',
      accent: 'blue',
      gateRole: 'none',
      systemKey: 'skip-gate',
      detail: {
        tech: 'Hash-equality branch. Identical bytes skip layers 2·3·4·5·8 (each skip logged); 6·7 always run — TLS, headers and per-UA responses are invisible to a content hash.',
        math: 'hash == baseline ?  skip 2·3·4·5·8  :  run all',
      },
    },

    // ---- gated analyzers ----
    {
      id: 'layer2',
      kind: 'layer',
      label: 'DOM Structure',
      accent: 'blue',
      gateRole: 'gated',
      index: '02',
      systemKey: 'layer2_dom_structure',
      detail: {
        tech: 'Diffs the suppressed DOM tree vs baseline: injected <script>/<iframe> nodes, and elements hidden via display:none or off-screen positioning.',
      },
    },
    {
      id: 'layer3',
      kind: 'layer',
      label: 'Link & Resource',
      accent: 'blue',
      gateRole: 'gated',
      index: '03',
      systemKey: 'layer3_links',
      detail: {
        tech: 'Compares outbound links, form actions and external resource origins (scripts, styles, images) against baseline; flags newly-introduced hosts.',
      },
    },
    {
      id: 'layer4',
      kind: 'layer',
      label: 'Visual Diff',
      accent: 'orange',
      gateRole: 'gated',
      index: '04',
      systemKey: 'layer4_visual_diff',
      detail: {
        tech: 'Structural similarity + perceptual/difference hashes over bbox-masked grayscale screenshots. Dynamic regions masked before scoring.',
        math: 'SSIM·0.7 + (pHash, dHash)·0.3',
      },
    },
    {
      id: 'layer5',
      kind: 'layer',
      label: 'Signatures',
      accent: 'orange',
      gateRole: 'gated',
      index: '05',
      systemKey: 'layer5_signatures',
      detail: {
        tech: 'Scans newly-appeared visible text for defacement markers: weighted phrase list, profanity burst detection, and Unicode-script-flip heuristics.',
        math: 'weighted phrases + profanity burst + Unicode script flip',
      },
    },
    {
      id: 'layer8',
      kind: 'layer',
      label: 'Text Semantics',
      accent: 'orange',
      gateRole: 'gated',
      index: '08',
      systemKey: 'layer8_semantics',
      detail: {
        tech: 'Local MiniLM-L6-v2 embedding; cosine drift from baseline plus aggression lexicon and topic-shift keywords. Inference stays on-host.',
        math: 'MiniLM cosine drift + aggression lexicon + topic keywords',
      },
    },

    // ---- always-run analyzers ----
    {
      id: 'layer6',
      kind: 'always',
      label: 'Security Metadata',
      accent: 'red',
      gateRole: 'always',
      index: '06',
      systemKey: 'layer6_security_metadata',
      detail: {
        tech: 'Inspects TLS cert (issuer/subject), security headers (HSTS, CSP, CORS) and robots.txt for shifts/downgrades. Runs on every scan, gate-independent.',
      },
    },
    {
      id: 'layer7',
      kind: 'always',
      label: 'Cloaking',
      accent: 'red',
      gateRole: 'always',
      index: '07',
      systemKey: 'layer7_cloaking',
      detail: {
        tech: 'UA-rotated fetches (Googlebot / mobile / desktop); Jaccard divergence between crawler responses and the desktop reference. Runs every scan.',
        math: 'Jaccard divergence: crawler vs desktop reference',
      },
    },

    // ---- fusion & score ----
    {
      id: 'fusion',
      kind: 'fusion',
      label: 'Risk Fusion',
      accent: 'purple',
      gateRole: 'none',
      index: '09',
      systemKey: 'layer9_fusion',
      detail: {
        tech: 'Seed-fitted deterministic logistic regression over the eight sub-scores → one calibrated 0.0–1.0 risk. Each layer isolated in try/except; a crash sets its score to none.',
        math: 'logistic_regression(L1…L8) → 0.0–1.0',
      },
    },
    {
      id: 'score',
      kind: 'score',
      label: 'Fused Risk',
      accent: 'green',
      gateRole: 'none',
      systemKey: 'fused_risk',
      detail: {
        tech: 'Material-change threshold 0.15. Crossing it tightens cadence and can gate guarded remediation; higher scores raise alerts.',
        math: '< 0.15 stable · ≥ 0.15 material change · high = defacement',
      },
    },
  ],

  edges: [
    { source: 'url', target: 'capture', accent: 'neutral' },
    { source: 'capture', target: 'layer1', accent: 'neutral' },
    { source: 'layer1', target: 'gate', accent: 'blue' },

    // decision → gated analyzers
    { source: 'gate', target: 'layer2', branch: 'gated', accent: 'blue' },
    { source: 'gate', target: 'layer3', branch: 'gated', accent: 'blue' },
    { source: 'gate', target: 'layer4', branch: 'gated', accent: 'orange' },
    { source: 'gate', target: 'layer5', branch: 'gated', accent: 'orange' },
    { source: 'gate', target: 'layer8', branch: 'gated', accent: 'orange' },
    // decision → always-run analyzers
    { source: 'gate', target: 'layer6', branch: 'always', accent: 'red' },
    { source: 'gate', target: 'layer7', branch: 'always', accent: 'red' },

    // analyzers → fusion
    { source: 'layer2', target: 'fusion', branch: 'gated', accent: 'blue' },
    { source: 'layer3', target: 'fusion', branch: 'gated', accent: 'blue' },
    { source: 'layer4', target: 'fusion', branch: 'gated', accent: 'orange' },
    { source: 'layer5', target: 'fusion', branch: 'gated', accent: 'orange' },
    { source: 'layer8', target: 'fusion', branch: 'gated', accent: 'orange' },
    { source: 'layer6', target: 'fusion', branch: 'always', accent: 'red' },
    { source: 'layer7', target: 'fusion', branch: 'always', accent: 'red' },

    { source: 'fusion', target: 'score', accent: 'green' },
  ],
};
