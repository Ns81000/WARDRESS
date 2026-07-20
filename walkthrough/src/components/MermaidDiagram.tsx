import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import type { FlowNodeSpec, FlowSpec } from '../flows/types';
import { buildMermaid } from '../lib/mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'loose',
  fontFamily:
    '"Instrument Sans Variable", "Inter Variable", ui-sans-serif, system-ui, sans-serif',
  flowchart: { curve: 'basis', nodeSpacing: 44, rankSpacing: 74, padding: 12, htmlLabels: true },
  themeVariables: {
    background: 'transparent',
    lineColor: '#4a4f52',
    primaryColor: 'transparent',
    edgeLabelBackground: '#0c0d0e',
  },
});

interface Props {
  flow: FlowSpec;
  gateSkipped: boolean;
  selectedId: string | null;
  onSelect: (node: FlowNodeSpec) => void;
}

interface Tip {
  text: string;
  x: number;
  y: number;
}

// Mermaid ids look like "<renderId>-flowchart-<userId>-<counter>"
// (e.g. "wd-mermaid-0-flowchart-layer1-2"). Pull the userId back out.
function userIdOf(gid: string): string | null {
  const m = /flowchart-(.+)-\d+$/.exec(gid);
  return m ? m[1] : null;
}

let renderSeq = 0;

export function MermaidDiagram({ flow, gateSkipped, selectedId, onSelect }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);

  useEffect(() => {
    let cancelled = false;
    const host = hostRef.current;
    if (!host) return;

    const specById = new Map(flow.nodes.map((n) => [n.id, n]));
    const { code } = buildMermaid(flow, gateSkipped);
    const id = `wd-mermaid-${renderSeq++}`;

    mermaid
      .render(id, code)
      .then(({ svg }) => {
        if (cancelled || !hostRef.current) return;
        hostRef.current.innerHTML = svg;

        const svgEl = hostRef.current.querySelector('svg');
        if (!svgEl) return;
        svgEl.removeAttribute('width');
        svgEl.removeAttribute('height');
        svgEl.style.width = '100%';
        svgEl.style.height = '100%';
        svgEl.style.maxWidth = '100%';

        // Wire each rendered node back to its spec for hover + click.
        hostRef.current.querySelectorAll<SVGGElement>('g.node').forEach((g) => {
          const uid = userIdOf(g.id);
          const spec = uid ? specById.get(uid) : undefined;
          if (!spec) return;

          g.style.cursor = 'pointer';
          g.classList.add('wd-node');
          if (spec.id === selectedId) g.classList.add('wd-node--active');

          g.addEventListener('mouseenter', (ev) => {
            const rect = hostRef.current!.getBoundingClientRect();
            const me = ev as MouseEvent;
            setTip({ text: spec.detail.plain, x: me.clientX - rect.left, y: me.clientY - rect.top });
          });
          g.addEventListener('mousemove', (ev) => {
            const rect = hostRef.current!.getBoundingClientRect();
            const me = ev as MouseEvent;
            setTip((t) => (t ? { ...t, x: me.clientX - rect.left, y: me.clientY - rect.top } : t));
          });
          g.addEventListener('mouseleave', () => setTip(null));
          g.addEventListener('click', (ev) => {
            ev.stopPropagation();
            setTip(null);
            onSelect(spec);
          });
        });
      })
      .catch((err) => {
        // Rendering should never hard-fail the page; surface it quietly.
        console.error('mermaid render failed', err);
        if (hostRef.current) {
          hostRef.current.innerHTML =
            '<p style="color:#ff2047;font-family:monospace;padding:1rem">diagram failed to render</p>';
        }
      });

    return () => {
      cancelled = true;
    };
  }, [flow, gateSkipped, selectedId, onSelect]);

  return (
    <div className="relative h-full w-full">
      <div ref={hostRef} className="wd-mermaid-host h-full w-full" />
      {tip && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-30 max-w-[260px] rounded-[9px] border border-hairline-strong bg-surface-elevated/95 px-3 py-2 text-[12.5px] leading-snug text-body shadow-lg backdrop-blur-xl"
          style={{ left: tip.x + 14, top: tip.y + 14 }}
        >
          {tip.text}
          <span className="mt-1 block font-mono text-[10px] text-ash">click for the full story →</span>
        </div>
      )}
    </div>
  );
}
