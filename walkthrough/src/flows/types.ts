// ============================================================
// Flow data contract.
//
// Every explainer (Detection Pipeline, Adaptive Cadence, and any
// future feature walkthrough) is a plain, typed data object that
// conforms to `FlowSpec`. The engine (FlowCanvas + step machine)
// renders any FlowSpec without change, so adding a new explainer is
// pure content: write one more file, register it in the tab list.
// ============================================================

export type Accent = 'blue' | 'orange' | 'red' | 'green' | 'neutral';

/** How a node behaves relative to the Content-Hash gate. */
export type GateRole =
  | 'always' // runs on every scan regardless of the gate (e.g. security, cloaking)
  | 'gated' // skipped when the hash matches the baseline
  | 'none'; // not subject to the gate (inputs, capture, fusion, score)

/** A labelled block inside a node's detail panel. */
export interface DetailBlock {
  label: string;
  body: string;
}

export interface FlowNodeSpec {
  id: string;
  /** Display kind — drives which custom node component renders. */
  kind: 'io' | 'stage' | 'layer' | 'fusion' | 'score';
  title: string;
  /** Short tagline shown on the node face. */
  tagline: string;
  accent: Accent;
  gateRole: GateRole;
  /** Optional layer number (Fraunces numeral on the node face). */
  index?: string;
  /** Machine key, e.g. `layer4_visual_diff` — shown mono on the face. */
  systemKey?: string;
  /** Canvas position. Hand-placed so the graph reads as designed. */
  position: { x: number; y: number };
  /** Which step (0-based) this node activates on in step-through mode. */
  step: number;
  /** Rich deep-dive, revealed in the side panel on click. */
  detail: {
    plain: string; // one-line, plain-English "what it watches"
    blocks: DetailBlock[]; // How it works / What trips it / The math / Input scope
    math?: string; // mono chip, e.g. "SSIM·0.7 + (pHash,dHash)·0.3"
    inputScope?: string; // original / suppressed HTML / masked screenshot / transport
  };
}

export interface FlowEdgeSpec {
  id: string;
  source: string;
  target: string;
  /** Edge belongs to a gate branch — dims when that branch is skipped. */
  branch?: 'gated' | 'always';
  /** Step at which the signal travels this edge. */
  step: number;
  accent?: Accent;
}

export interface FlowSpec {
  id: string;
  /** Tab label. */
  name: string;
  /** One-line summary under the title. */
  blurb: string;
  /** Ordered step captions shown in the step control bar / narration. */
  steps: string[];
  nodes: FlowNodeSpec[];
  edges: FlowEdgeSpec[];
  /** Whether this flow exposes the bytes-changed / identical gate toggle. */
  hasGate: boolean;
}
