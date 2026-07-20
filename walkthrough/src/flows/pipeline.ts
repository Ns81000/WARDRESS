import type { FlowSpec } from './types';

// ============================================================
// Detection Pipeline — the 9-layer scan, URL → fused risk score.
//
// Every technical claim here is sourced from the Wardress
// detection-layers documentation:
//   - Layer 1 hashes ORIGINAL html (SHA-256, normalized) and gates
//     layers 2/3/4/5/8 when it matches the baseline.
//   - Layers 6 & 7 always run (transport + per-UA data are invisible
//     to the content hash).
//   - Layer 4: SSIM·0.7 + (pHash,dHash)·0.3 on bbox-masked grayscale.
//   - Layer 8: MiniLM cosine drift on suppressed text.
//   - Layer 9: seed-fitted logistic regression → calibrated 0.0–1.0.
//   - Material-change threshold 0.15.
// ============================================================

// Vertical rhythm for the parallel analyzer column.
const COL_X = 760;
const ROW = (n: number) => 40 + n * 116;
const SPINE_Y = ROW(3); // vertical centre of the analyzer stack

export const pipelineFlow: FlowSpec = {
  id: 'pipeline',
  name: 'Detection Pipeline',
  blurb: 'One scan, nine independent witnesses, fused into a single calibrated risk score.',
  steps: [
    'A monitored URL comes due for a scan.',
    'Playwright fetches and renders the page, capturing HTML and a screenshot.',
    'Layer 1 hashes the normalized HTML. Identical bytes gate five layers.',
    'The surviving analyzers run in parallel — structure, links, pixels, text, transport.',
    'Layer 9 fuses all eight sub-scores with a calibrated model.',
    'One number, 0.0–1.0 — the risk score that trips alerts and tightens cadence.',
  ],
  hasGate: true,

  nodes: [
    // ---- inputs & capture ----
    {
      id: 'url',
      kind: 'io',
      title: 'Monitored URL',
      tagline: 'https://your-site.example',
      accent: 'neutral',
      gateRole: 'none',
      position: { x: 0, y: SPINE_Y },
      step: 0,
      detail: {
        plain: 'The page you asked Wardress to watch, frozen once as a trusted baseline.',
        inputScope: 'Your site — fetched read-only',
        blocks: [
          {
            label: 'How it works',
            body: 'When you enrol a site, Wardress records a baseline: the normalized HTML, the network references, a masked screenshot, and the meaning of the visible text. Every later scan is measured against that frozen baseline, never against the previous scan — so slow drift can never quietly redefine "normal".',
          },
          {
            label: 'Cadence',
            body: 'A scan is scheduled adaptively. Celery Beat ticks every 60 seconds and dispatches any site whose next-scan time is due. Nothing about your page is stored off your own infrastructure.',
          },
        ],
      },
    },
    {
      id: 'capture',
      kind: 'stage',
      title: 'Capture',
      tagline: 'Playwright · render · screenshot',
      accent: 'neutral',
      gateRole: 'none',
      systemKey: 'playwright',
      position: { x: 340, y: SPINE_Y },
      step: 1,
      detail: {
        plain: 'A real browser loads the page exactly as a visitor would, then hands the pipeline its raw materials.',
        inputScope: 'Original HTML + rendered screenshot',
        blocks: [
          {
            label: 'How it works',
            body: 'Playwright drives a headless Chromium instance to fetch and fully render the page — executing JavaScript, applying CSS, settling the layout. It produces the original HTML, a set of UA-rotated fetches, and a grayscale screenshot with dynamic regions masked out.',
          },
          {
            label: 'Why a real browser',
            body: 'A plain HTTP fetch sees only the server\'s first response. Modern defacements often inject content after load, or serve different markup to browsers than to crawlers. Rendering like a visitor is the only way to see what a visitor sees.',
          },
        ],
      },
    },

    // ---- the gate ----
    {
      id: 'layer1',
      kind: 'layer',
      title: 'Content Hash',
      tagline: 'The gate — identical bytes skip the rest.',
      accent: 'blue',
      gateRole: 'always',
      index: '01',
      systemKey: 'layer1_hash',
      position: { x: 460, y: SPINE_Y },
      step: 2,
      detail: {
        plain: 'A single fingerprint of the whole page. If it is unchanged, most of the pipeline can safely be skipped.',
        math: 'SHA-256(normalize(html)) → 0.0 / 1.0',
        inputScope: 'Original HTML (never suppressed)',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 1 conservatively normalizes the HTML and computes a SHA-256 hash, producing a binary result: 0.0 if the fingerprint matches the baseline, 1.0 if it differs. It deliberately hashes the ORIGINAL content, not the noise-suppressed copy, so tampering can never be hidden behind suppression rules.',
          },
          {
            label: 'The gate',
            body: 'This is the pipeline\'s efficiency gate. If the hash matches, layers 2, 3, 4, 5 and 8 are skipped — byte-identical content cannot differ structurally, in links, visually, in signatures, or semantically. Each skip is logged with its reason. Layers 6 and 7 always run anyway, because TLS, headers and per-user-agent responses are invisible to a content hash.',
          },
          {
            label: 'What trips it',
            body: 'Any change to the served HTML at all — a single injected script tag, an altered headline, a new hidden iframe — flips the hash to 1.0 and wakes the full pipeline.',
          },
        ],
      },
    },

    // ---- gated analyzers ----
    {
      id: 'layer2',
      kind: 'layer',
      title: 'DOM Structure',
      tagline: 'Injected scripts, iframes, hidden nodes.',
      accent: 'blue',
      gateRole: 'gated',
      index: '02',
      systemKey: 'layer2_dom_structure',
      position: { x: COL_X, y: ROW(0) },
      step: 3,
      detail: {
        plain: 'Watches the shape of the page for structure that was quietly added or torn out.',
        math: 'lxml tag-tree churn + new <script>/<iframe>/hidden',
        inputScope: 'Suppressed HTML',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 2 diffs the lxml tag-tree of the current page against the baseline, measuring how much of the structure churned, and specifically counting newly introduced <script> tags, <iframe>s, and force-hidden elements.',
          },
          {
            label: 'What trips it',
            body: 'A hidden <iframe> pointing at an attacker domain, an injected <script> that was never in the baseline, or a block of content shoved off-screen with inline styles — the classic footprints of an injection.',
          },
        ],
      },
    },
    {
      id: 'layer3',
      kind: 'layer',
      title: 'Link Audit',
      tagline: 'The exfiltration fingerprint.',
      accent: 'blue',
      gateRole: 'gated',
      index: '03',
      systemKey: 'layer3_link_audit',
      position: { x: COL_X, y: ROW(1) },
      step: 3,
      detail: {
        plain: 'Tracks every outbound reference so new destinations can\'t slip in unnoticed.',
        math: 'set-diff(script,a,link,iframe,form) — new external domains dominate',
        inputScope: 'Suppressed HTML',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 3 takes the set difference of all script, anchor, link, iframe and form references between baseline and current page. New references to external domains are weighted most heavily.',
          },
          {
            label: 'What trips it',
            body: 'A form whose action now posts to an unfamiliar host, a stylesheet or script pulled from a new CDN, or fresh outbound links to a domain that was never referenced before — the signature of data exfiltration or a redirect.',
          },
        ],
      },
    },
    {
      id: 'layer4',
      kind: 'layer',
      title: 'Visual Diff',
      tagline: 'Sees the defacement as pixels.',
      accent: 'orange',
      gateRole: 'gated',
      index: '04',
      systemKey: 'layer4_visual_diff',
      position: { x: COL_X, y: ROW(2) },
      step: 3,
      detail: {
        plain: 'Compares what the page looks like, pixel for pixel, against the baseline picture.',
        math: 'SSIM·0.7 + (pHash, dHash)·0.3',
        inputScope: 'Bbox-masked grayscale screenshots',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 4 combines structural similarity (SSIM, weighted 0.7) with perceptual and difference hashes (pHash and dHash, together weighted 0.3) over grayscale screenshots. Known-dynamic regions are masked by bounding box first, so rotating banners and ads don\'t register as change.',
          },
          {
            label: 'What trips it',
            body: 'A classic full-page defacement — the "you\'ve been hacked" splash — scores near the top even if the underlying HTML is cleverly disguised. The eye can\'t be fooled by markup tricks.',
          },
        ],
      },
    },
    {
      id: 'layer5',
      kind: 'layer',
      title: 'Signatures',
      tagline: 'Defacement phrases, profanity, script flips.',
      accent: 'orange',
      gateRole: 'gated',
      index: '05',
      systemKey: 'layer5_signatures',
      position: { x: COL_X, y: ROW(3) },
      step: 3,
      detail: {
        plain: 'Reads the newly-appeared text for the vocabulary of a defacement.',
        math: 'weighted phrases + profanity burst + Unicode script flip',
        inputScope: 'New visible text',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 5 scores only the text that is new relative to the baseline, looking for weighted defacement phrases, sudden bursts of profanity, and Unicode script flips (for example Latin characters swapped for lookalike Cyrillic).',
          },
          {
            label: 'What trips it',
            body: 'Hacktivist slogans, "hacked by" signatures, a wall of profanity, or a headline where letters have been silently substituted with foreign-script lookalikes to evade naive keyword filters.',
          },
        ],
      },
    },
    {
      id: 'layer8',
      kind: 'layer',
      title: 'Text Semantics',
      tagline: 'Measures meaning drift from the baseline.',
      accent: 'orange',
      gateRole: 'gated',
      index: '08',
      systemKey: 'layer8_semantics',
      position: { x: COL_X, y: ROW(4) },
      step: 3,
      detail: {
        plain: 'Understands whether the page still means the same thing, even when the wording changes.',
        math: 'MiniLM cosine drift + aggression lexicon + topic keywords',
        inputScope: 'Suppressed text (local inference)',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 8 embeds the visible text with a local MiniLM-L6-v2 model and measures cosine drift from the baseline embedding, combined with an aggression lexicon and defacement topic keywords. Inference runs entirely on your host — no text leaves your infrastructure.',
          },
          {
            label: 'What trips it',
            body: 'A page whose words changed but whose HTML barely moved — a subtle content swap, a rewritten paragraph pushing a scam, or a topic shift from "storefront" to "political message" that keyword rules would miss.',
          },
        ],
      },
    },

    // ---- always-run analyzers ----
    {
      id: 'layer6',
      kind: 'layer',
      title: 'Security Metadata',
      tagline: 'TLS, HSTS, CSP, CORS, robots.txt.',
      accent: 'red',
      gateRole: 'always',
      index: '06',
      systemKey: 'layer6_security_metadata',
      position: { x: COL_X, y: ROW(5) + 24 },
      step: 3,
      detail: {
        plain: 'Watches the transport layer and security headers that a content hash can never see.',
        inputScope: 'TLS + headers + robots.txt',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 6 inspects the TLS certificate (issuer and subject), the security headers (HSTS, CSP, CORS), and robots.txt, flagging certificate shifts, header downgrades, and robots changes. It runs on every single scan, even when the content hash matches.',
          },
          {
            label: 'What trips it',
            body: 'A certificate suddenly issued by a different authority, a CSP or HSTS header quietly dropped, or CORS relaxed to allow any origin — the fingerprints of a man-in-the-middle or a server-level compromise that leaves the HTML untouched.',
          },
        ],
      },
    },
    {
      id: 'layer7',
      kind: 'layer',
      title: 'Cloaking',
      tagline: 'Content served only to crawlers, not visitors.',
      accent: 'red',
      gateRole: 'always',
      index: '07',
      systemKey: 'layer7_cloaking',
      position: { x: COL_X, y: ROW(6) + 24 },
      step: 3,
      detail: {
        plain: 'Catches pages that show one thing to Google and something else to real people.',
        math: 'Jaccard divergence: Googlebot / mobile vs desktop reference',
        inputScope: 'User-agent-rotated raw fetches',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 7 fetches the page under rotated user agents (Googlebot, mobile, desktop) and measures the Jaccard divergence between the crawler responses and the desktop reference. It runs on every scan.',
          },
          {
            label: 'What trips it',
            body: 'Cloaking attacks that serve clean content to search-engine crawlers — to preserve ranking — while serving spam, malware or a defacement to ordinary visitors. The divergence between the two exposes the trick.',
          },
        ],
      },
    },

    // ---- fusion & score ----
    {
      id: 'fusion',
      kind: 'fusion',
      title: 'Risk Fusion',
      tagline: 'Eight sub-scores → one calibrated number.',
      accent: 'green',
      gateRole: 'none',
      index: '09',
      systemKey: 'layer9_fusion',
      position: { x: COL_X + 420, y: SPINE_Y },
      step: 4,
      detail: {
        plain: 'Weighs all eight verdicts together into a single trustworthy score, instead of tripping on any one alarm.',
        math: 'logistic_regression(L1…L8) → 0.0–1.0',
        inputScope: 'Layers 1–8 sub-scores',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 9 feeds the eight sub-scores into a deterministic, seed-fitted logistic regression that outputs one calibrated risk score between 0.0 and 1.0. Because it is calibrated rather than a brittle threshold, a single noisy layer can\'t raise a false alarm, and a quiet compromise across several layers still adds up.',
          },
          {
            label: 'What the number does',
            body: 'The fused score is the value that trips alerts, tightens the scan cadence, and gates guarded remediation. A material change is anything at or above 0.15 — deliberately below any sane flag threshold, but above ordinary dynamic-content noise.',
          },
          {
            label: 'Resilience',
            body: 'Every layer runs in its own try/except. If one crashes, it records the error, sets its score to none, and the rest of the pipeline carries on — fusion simply works with the layers it has.',
          },
        ],
      },
    },
    {
      id: 'score',
      kind: 'score',
      title: 'Fused Risk',
      tagline: 'baseline locked',
      accent: 'green',
      gateRole: 'none',
      systemKey: 'fused_risk',
      position: { x: COL_X + 760, y: SPINE_Y },
      step: 5,
      detail: {
        plain: 'The one number you actually watch — and the actions it sets in motion.',
        math: '< 0.15 stable · ≥ 0.15 material change · high = defacement',
        blocks: [
          {
            label: 'How to read it',
            body: 'Below 0.15 the page is considered stable. At or above 0.15 Wardress records a material change. As the score climbs it crosses into defacement territory, raising alerts through your configured channels.',
          },
          {
            label: 'What it triggers',
            body: 'Crossing the material-change threshold tightens the next scan interval to a quarter of the base. Clean scans afterwards relax it back gradually. High scores raise alerts and gate guarded remediation — a human stays in the loop for anything destructive.',
          },
        ],
      },
    },
  ],

  edges: [
    { id: 'e-url-cap', source: 'url', target: 'capture', step: 0, accent: 'neutral' },
    { id: 'e-cap-l1', source: 'capture', target: 'layer1', step: 1, accent: 'neutral' },

    // gate → gated analyzers
    { id: 'e-l1-l2', source: 'layer1', target: 'layer2', step: 2, branch: 'gated', accent: 'blue' },
    { id: 'e-l1-l3', source: 'layer1', target: 'layer3', step: 2, branch: 'gated', accent: 'blue' },
    { id: 'e-l1-l4', source: 'layer1', target: 'layer4', step: 2, branch: 'gated', accent: 'orange' },
    { id: 'e-l1-l5', source: 'layer1', target: 'layer5', step: 2, branch: 'gated', accent: 'orange' },
    { id: 'e-l1-l8', source: 'layer1', target: 'layer8', step: 2, branch: 'gated', accent: 'orange' },
    // gate → always-run analyzers
    { id: 'e-l1-l6', source: 'layer1', target: 'layer6', step: 2, branch: 'always', accent: 'red' },
    { id: 'e-l1-l7', source: 'layer1', target: 'layer7', step: 2, branch: 'always', accent: 'red' },

    // analyzers → fusion
    { id: 'e-l2-f', source: 'layer2', target: 'fusion', step: 3, branch: 'gated', accent: 'blue' },
    { id: 'e-l3-f', source: 'layer3', target: 'fusion', step: 3, branch: 'gated', accent: 'blue' },
    { id: 'e-l4-f', source: 'layer4', target: 'fusion', step: 3, branch: 'gated', accent: 'orange' },
    { id: 'e-l5-f', source: 'layer5', target: 'fusion', step: 3, branch: 'gated', accent: 'orange' },
    { id: 'e-l8-f', source: 'layer8', target: 'fusion', step: 3, branch: 'gated', accent: 'orange' },
    { id: 'e-l6-f', source: 'layer6', target: 'fusion', step: 3, branch: 'always', accent: 'red' },
    { id: 'e-l7-f', source: 'layer7', target: 'fusion', step: 3, branch: 'always', accent: 'red' },

    { id: 'e-f-score', source: 'fusion', target: 'score', step: 4, accent: 'green' },
  ],
};
