import type { Accent, FlowSpec, NodeKind } from '../flows/types';

// ============================================================
// Compiles a FlowSpec into Mermaid flowchart source, plus the
// classDef styling that gives each node its Wardress skin. Shapes
// are chosen per node kind so the graph reads by silhouette:
//   input → parallelogram, stage → stadium, decision → rhombus,
//   layer → rectangle, always → hexagon, fusion → trapezoid,
//   score → circle, note → rounded.
// ============================================================

// Fills use 8-digit hex (alpha baked in) — Mermaid's classDef parser treats
// the commas inside rgba(...) as property separators and rejects them.
const ACCENT_HEX: Record<Accent, { stroke: string; fill: string; text: string }> = {
  blue: { stroke: '#3b9eff', fill: '#3b9eff1f', text: '#cfe6ff' },
  orange: { stroke: '#ff801f', fill: '#ff801f1f', text: '#ffd9b8' },
  red: { stroke: '#ff2047', fill: '#ff20471f', text: '#ffc2cd' },
  green: { stroke: '#11ff99', fill: '#11ff991f', text: '#b6ffe4' },
  purple: { stroke: '#a97bff', fill: '#a97bff24', text: '#e3d5ff' },
  neutral: { stroke: '#888e90', fill: '#ffffff0d', text: '#d6d9da' },
};

// Wrap a label in the Mermaid delimiters for the shape of a given kind.
function shape(kind: NodeKind, id: string, text: string): string {
  const t = text.replace(/"/g, '&quot;');
  switch (kind) {
    case 'input':
      return `${id}[/"${t}"/]`; // parallelogram
    case 'stage':
      return `${id}(["${t}"])`; // stadium
    case 'decision':
      return `${id}{"${t}"}`; // rhombus
    case 'always':
      return `${id}{{"${t}"}}`; // hexagon
    case 'fusion':
      return `${id}[\\"${t}"\\]`; // trapezoid (wider top)
    case 'score':
      return `${id}(("${t}"))`; // circle
    case 'note':
      return `${id}("${t}")`; // rounded
    case 'layer':
    default:
      return `${id}["${t}"]`; // rectangle
  }
}

export interface BuiltFlow {
  code: string;
  /** node id → accent, so the overlay can theme tooltips to match. */
  accentById: Record<string, Accent>;
}

export function buildMermaid(flow: FlowSpec, gateSkipped: boolean): BuiltFlow {
  const lines: string[] = [`flowchart ${flow.direction}`];
  const accentById: Record<string, Accent> = {};

  // nodes
  for (const n of flow.nodes) {
    accentById[n.id] = n.accent;
    const label = n.index ? `${n.index} · ${n.label}` : n.label;
    lines.push(`  ${shape(n.kind, n.id, label)}`);
  }

  // edges — dim the gated branch when the hash is identical
  flow.edges.forEach((e, i) => {
    const dim = gateSkipped && e.branch === 'gated';
    const arrow = dim ? '-.->' : '-->';
    const seg = e.label ? `${arrow}|"${e.label}"|` : arrow;
    lines.push(`  ${e.source} ${seg} ${e.target}`);
    // tag the edge index so we can class it
    if (dim) lines.push(`  linkStyle ${i} stroke:#2a2a2e,stroke-width:1px,opacity:0.35`);
  });

  // classDefs per accent + a skipped variant
  const kinds = new Set(flow.nodes.map((n) => n.accent));
  for (const a of kinds) {
    const c = ACCENT_HEX[a];
    lines.push(
      `  classDef ${a} fill:${c.fill},stroke:${c.stroke},stroke-width:1.5px,color:${c.text};`,
    );
  }
  lines.push(
    `  classDef skipped fill:#ffffff05,stroke:#2a2a2e,stroke-width:1px,color:#5b5f61,stroke-dasharray:4 3;`,
  );

  // assign classes
  for (const n of flow.nodes) {
    const skipped = gateSkipped && n.gateRole === 'gated';
    lines.push(`  class ${n.id} ${skipped ? 'skipped' : n.accent};`);
  }

  return { code: lines.join('\n'), accentById };
}
