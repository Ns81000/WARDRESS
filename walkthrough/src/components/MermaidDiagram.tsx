import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import type { FlowSpec } from '../flows/types';
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
}

interface Tip {
  tech: string;
  math?: string;
  x: number;
  y: number;
}

// Mermaid ids look like "<renderId>-flowchart-<userId>-<counter>".
function userIdOf(gid: string): string | null {
  const m = /flowchart-(.+)-\d+$/.exec(gid);
  return m ? m[1] : null;
}

let renderSeq = 0;

export function MermaidDiagram({ flow, gateSkipped }: Props) {
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

        // Wire each rendered node back to its spec for the hover tooltip.
        hostRef.current.querySelectorAll<SVGGElement>('g.node').forEach((g) => {
          const uid = userIdOf(g.id);
          const spec = uid ? specById.get(uid) : undefined;
          if (!spec) return;

          g.classList.add('wd-node');

          const show = (ev: MouseEvent) => {
            const rect = hostRef.current!.getBoundingClientRect();
            setTip({
              tech: spec.detail.tech,
              math: spec.detail.math,
              x: ev.clientX - rect.left,
              y: ev.clientY - rect.top,
            });
          };
          g.addEventListener('mouseenter', show as EventListener);
          g.addEventListener('mousemove', show as EventListener);
          g.addEventListener('mouseleave', () => setTip(null));
        });
      })
      .catch((err) => {
        console.error('mermaid render failed', err);
        if (hostRef.current) {
          hostRef.current.innerHTML =
            '<p style="color:#ff2047;font-family:monospace;padding:1rem">diagram failed to render</p>';
        }
      });

    return () => {
      cancelled = true;
    };
  }, [flow, gateSkipped]);

  return (
    <div className="relative h-full w-full">
      <div ref={hostRef} className="wd-mermaid-host h-full w-full" />
      {tip && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-30 max-w-[320px] rounded-[10px] border border-hairline-strong bg-surface-elevated/95 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-body shadow-lg backdrop-blur-xl"
          style={{ left: tip.x + 14, top: tip.y + 14 }}
        >
          {tip.tech}
          {tip.math && (
            <span className="mt-1.5 block font-mono text-[11px] text-ash">{tip.math}</span>
          )}
        </div>
      )}
    </div>
  );
}
