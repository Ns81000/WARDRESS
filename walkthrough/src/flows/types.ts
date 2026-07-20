// ============================================================
// Flow data contract.
//
// Every explainer (Detection Pipeline, Adaptive Cadence, and any
// future feature walkthrough) is a plain, typed data object that
// conforms to `FlowSpec`. The engine compiles a FlowSpec into a
// Mermaid flowchart, then layers hover tooltips + a click-through
// detail panel on top of the rendered SVG. Adding a new explainer
// is pure content: write one more file, register it in the tab list.
// ============================================================

export type Accent = 'blue' | 'orange' | 'red' | 'green' | 'purple' | 'neutral';

/** How a node behaves relative to the Content-Hash gate. */
export type GateRole =
  | 'always' // runs on every scan regardless of the gate (e.g. security, cloaking)
  | 'gated' // skipped when the hash matches the baseline
  | 'none'; // not subject to the gate (inputs, capture, decision, fusion, score)

/**
 * Visual vocabulary — each kind maps to a distinct Mermaid node shape so the
 * graph reads by silhouette, not just colour:
 *   input     → parallelogram   (data in/out)
 *   stage     → stadium         (a processing step)
 *   decision  → rhombus         (the skip/run branch)
 *   layer     → rectangle       (a detection analyzer)
 *   always    → hexagon         (analyzer that never skips)
 *   fusion    → trapezoid        (many signals converge)
 *   score     → circle          (the single output number)
 *   note      → rounded         (an annotation, e.g. "layers skipped")
 */
export type NodeKind =
  | 'input'
  | 'stage'
  | 'decision'
  | 'layer'
  | 'always'
  | 'fusion'
  | 'score'
  | 'note';

/** A labelled block inside a node's detail panel. */
export interface DetailBlock {
  label: string;
  body: string;
}

export interface FlowNodeSpec {
  id: string;
  kind: NodeKind;
  /** Label drawn inside the node. Keep short — the shape is small. */
  label: string;
  accent: Accent;
  gateRole: GateRole;
  /** Optional layer numeral, prefixed onto the node label. */
  index?: string;
  /** Machine key, e.g. `layer4_visual_diff` — shown in the detail panel. */
  systemKey?: string;
  /** Rich deep-dive, revealed in the side panel on click. */
  detail: {
    plain: string; // one-line, plain-English "what it watches" — also the hover tooltip
    blocks: DetailBlock[]; // How it works / What trips it / etc.
    math?: string; // mono chip, e.g. "SSIM·0.7 + (pHash,dHash)·0.3"
    inputScope?: string; // original / suppressed HTML / masked screenshot / transport
  };
}

export interface FlowEdgeSpec {
  source: string;
  target: string;
  /** Optional edge label (e.g. the decision branch: "identical" / "changed"). */
  label?: string;
  /** Edge belongs to a gate branch — dims when that branch is skipped. */
  branch?: 'gated' | 'always';
  accent?: Accent;
}

export interface FlowSpec {
  id: string;
  /** Tab label. */
  name: string;
  /** One-line summary under the title. */
  blurb: string;
  /** Mermaid layout direction. */
  direction: 'LR' | 'TB';
  nodes: FlowNodeSpec[];
  edges: FlowEdgeSpec[];
  /** Whether this flow exposes the identical/changed gate toggle. */
  hasGate: boolean;
}
