import type { FlowSpec } from './types';

// ============================================================
// Detection Pipeline — the 9-layer scan, URL → fused risk score.
//
// Every technical claim here is sourced from the Wardress
// detection-layers documentation:
//   - Layer 1 hashes ORIGINAL html (SHA-256, normalized).
//   - The hash result drives a SKIP DECISION: identical bytes skip
//     layers 2/3/4/5/8; changed bytes run everything.
//   - Layers 6 & 7 always run (transport + per-UA data are invisible
//     to the content hash).
//   - Layer 4: SSIM·0.7 + (pHash,dHash)·0.3 on bbox-masked grayscale.
//   - Layer 8: MiniLM cosine drift on suppressed text.
//   - Layer 9: seed-fitted logistic regression → calibrated 0.0–1.0.
//   - Material-change threshold 0.15.
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
      label: 'Capture',
      accent: 'neutral',
      gateRole: 'none',
      systemKey: 'playwright',
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
        plain: 'A single fingerprint of the whole page — the fast first check.',
        math: 'SHA-256(normalize(html)) → 0.0 / 1.0',
        inputScope: 'Original HTML (never suppressed)',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 1 conservatively normalizes the HTML and computes a SHA-256 hash, producing a binary result: 0.0 if the fingerprint matches the baseline, 1.0 if it differs. It deliberately hashes the ORIGINAL content, not the noise-suppressed copy, so tampering can never be hidden behind suppression rules.',
          },
          {
            label: 'What trips it',
            body: 'Any change to the served HTML at all — a single injected script tag, an altered headline, a new hidden iframe — flips the hash to 1.0 and wakes the full pipeline.',
          },
        ],
      },
    },
    {
      // The explicit branch the user asked for: decide whether to skip.
      id: 'gate',
      kind: 'decision',
      label: 'Bytes changed?',
      accent: 'blue',
      gateRole: 'none',
      systemKey: 'skip-gate',
      detail: {
        plain: 'The efficiency gate: if the page is byte-for-byte identical, most analyzers can be safely skipped.',
        math: 'hash == baseline ?  skip 2·3·4·5·8  :  run all',
        blocks: [
          {
            label: 'How it works',
            body: 'The hash result decides the whole pipeline\'s shape. If the fingerprint matches the baseline, layers 2, 3, 4, 5 and 8 are skipped — byte-identical content cannot differ structurally, in links, visually, in signatures, or semantically. Each skip is logged with its reason.',
          },
          {
            label: 'What never skips',
            body: 'Layers 6 and 7 run on every scan regardless of this decision, because TLS certificates, security headers and per-user-agent responses are all invisible to a content hash. A page can be byte-identical yet served over a swapped certificate.',
          },
          {
            label: 'Try it',
            body: 'Flip the "Content hash" toggle above the diagram between "changed" and "identical" to watch the skipped branch dim out and the pipeline collapse to just the always-on analyzers.',
          },
        ],
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
        plain: 'Watches the shape of the page for structure that was quietly added or hidden.',
        inputScope: 'Suppressed HTML (noise removed)',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 2 diffs the DOM tree against the baseline after noise suppression, looking for injected <script> tags, new <iframe>s, and nodes hidden with display:none or off-screen positioning.',
          },
          {
            label: 'What trips it',
            body: 'A cryptominer injected as a script, an invisible iframe pulling in a phishing page, or SEO-spam links stuffed into a hidden div — the classic shapes of a quiet compromise.',
          },
        ],
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
        plain: 'Follows where the page now points — new domains, redirected forms, swapped scripts.',
        inputScope: 'Suppressed HTML (links & resources)',
        blocks: [
          {
            label: 'How it works',
            body: 'Layer 3 compares the set of outbound links, form actions, and external resource origins (scripts, stylesheets, images) against the baseline, flagging newly-introduced hosts.',
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
      label: 'Visual Diff',
      accent: 'orange',
      gateRole: 'gated',
      index: '04',
      systemKey: 'layer4_visual_diff',
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
      label: 'Signatures',
      accent: 'orange',
      gateRole: 'gated',
      index: '05',
      systemKey: 'layer5_signatures',
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
      label: 'Text Semantics',
      accent: 'orange',
      gateRole: 'gated',
      index: '08',
      systemKey: 'layer8_semantics',
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
      kind: 'always',
      label: 'Security Metadata',
      accent: 'red',
      gateRole: 'always',
      index: '06',
      systemKey: 'layer6_security_metadata',
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
      kind: 'always',
      label: 'Cloaking',
      accent: 'red',
      gateRole: 'always',
      index: '07',
      systemKey: 'layer7_cloaking',
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
      label: 'Risk Fusion',
      accent: 'purple',
      gateRole: 'none',
      index: '09',
      systemKey: 'layer9_fusion',
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
      label: 'Fused Risk',
      accent: 'green',
      gateRole: 'none',
      systemKey: 'fused_risk',
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
    { source: 'url', target: 'capture', accent: 'neutral' },
    { source: 'capture', target: 'layer1', accent: 'neutral' },
    { source: 'layer1', target: 'gate', accent: 'blue' },

    // decision → gated analyzers (the "changed" branch)
    { source: 'gate', target: 'layer2', label: 'changed', branch: 'gated', accent: 'blue' },
    { source: 'gate', target: 'layer3', branch: 'gated', accent: 'blue' },
    { source: 'gate', target: 'layer4', branch: 'gated', accent: 'orange' },
    { source: 'gate', target: 'layer5', branch: 'gated', accent: 'orange' },
    { source: 'gate', target: 'layer8', branch: 'gated', accent: 'orange' },
    // decision → always-run analyzers (taken on every scan)
    { source: 'gate', target: 'layer6', label: 'always', branch: 'always', accent: 'red' },
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
