import { useEffect, useMemo, useState } from 'react';
import { flows } from './flows';
import { MermaidDiagram } from './components/MermaidDiagram';
import { DetailPanel } from './components/DetailPanel';
import { TabBar } from './components/TabBar';
import { GateToggle, type GateMode } from './components/GateToggle';
import type { FlowNodeSpec } from './flows/types';

// Landing page origin under GitHub Pages (project subpath).
const LANDING_URL = '../';

// Shape legend — so the varied silhouettes read at a glance.
const LEGEND: { shape: string; label: string }[] = [
  { shape: 'parallelogram', label: 'input' },
  { shape: 'stadium', label: 'stage' },
  { shape: 'rhombus', label: 'decision' },
  { shape: 'rect', label: 'analyzer' },
  { shape: 'hexagon', label: 'always-on' },
  { shape: 'trapezoid', label: 'fusion' },
  { shape: 'circle', label: 'score' },
];

export function App() {
  const [activeId, setActiveId] = useState(flows[0].id);
  const [selected, setSelected] = useState<FlowNodeSpec | null>(null);
  const [gateMode, setGateMode] = useState<GateMode>('changed');

  const flow = useMemo(() => flows.find((f) => f.id === activeId) ?? flows[0], [activeId]);
  const gateSkipped = flow.hasGate && gateMode === 'identical';

  // Reset transient UI whenever the flow changes.
  useEffect(() => {
    setSelected(null);
    setGateMode('changed');
  }, [activeId]);

  // Escape closes the detail panel.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setSelected(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="flex h-full flex-col bg-canvas text-body">
      {/* ambient glow field, matching the landing page */}
      <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <div
          className="absolute left-1/2 top-[-320px] h-[720px] w-[720px] -translate-x-[55%] rounded-full"
          style={{ background: 'radial-gradient(circle, var(--color-glow-blue), transparent 68%)', filter: 'blur(120px)', opacity: 0.4 }}
        />
        <div
          className="absolute right-[-220px] top-[6%] h-[520px] w-[520px] rounded-full"
          style={{ background: 'radial-gradient(circle, var(--color-glow-orange), transparent 70%)', filter: 'blur(120px)', opacity: 0.28 }}
        />
      </div>

      {/* ===== header ===== */}
      <header className="relative z-10 flex shrink-0 items-center justify-between gap-4 border-b border-hairline px-6 py-3.5">
        <div className="flex items-center gap-3">
          <a href={LANDING_URL} className="flex items-center gap-2.5" aria-label="Back to Wardress">
            <img src="favicon.svg" alt="" width={24} height={24} />
            <span className="font-display-sans text-[15px] font-medium text-ink">Wardress</span>
          </a>
          <span className="h-4 w-px bg-hairline-strong" />
          <span className="font-mono text-[11px] uppercase tracking-[1.4px]" style={{ color: 'var(--color-ash)' }}>
            How it works
          </span>
        </div>

        <TabBar flows={flows} activeId={activeId} onSelect={setActiveId} />

        <a
          href={LANDING_URL}
          className="flex items-center gap-1.5 rounded-[8px] border border-hairline px-3 py-1.5 text-[13px] text-mute transition-colors hover:border-hairline-strong hover:text-ink"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          Landing
        </a>
      </header>

      {/* ===== title strip ===== */}
      <div className="relative z-10 flex shrink-0 items-end justify-between gap-6 px-6 pb-3 pt-4">
        <div>
          <h1 className="font-display text-[26px] leading-none text-ink" style={{ fontVariationSettings: '"opsz" 120' }}>
            {flow.name}
          </h1>
          <p className="mt-1.5 max-w-[64ch] text-[13.5px] text-charcoal">{flow.blurb}</p>
        </div>
        {flow.hasGate && <GateToggle mode={gateMode} onChange={setGateMode} />}
      </div>

      {/* ===== diagram ===== */}
      <div className="relative z-10 min-h-0 flex-1 px-4 pb-2">
        <div className="relative h-full w-full overflow-hidden rounded-[16px] border border-hairline bg-surface-card/40">
          <MermaidDiagram
            flow={flow}
            gateSkipped={gateSkipped}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
          />
          <DetailPanel node={selected} onClose={() => setSelected(null)} />

          {/* hover hint */}
          <div className="pointer-events-none absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-full border border-hairline bg-surface-card/90 px-4 py-1.5 text-[12px] text-mute backdrop-blur-xl">
            Hover a node for the short version · click it for the full story
          </div>
        </div>
      </div>

      {/* ===== shape legend ===== */}
      <div className="relative z-10 flex shrink-0 flex-wrap items-center justify-center gap-x-5 gap-y-2 px-6 pb-4 pt-1">
        {LEGEND.map((l) => (
          <div key={l.label} className="flex items-center gap-1.5">
            <LegendGlyph shape={l.shape} />
            <span className="font-mono text-[10.5px] uppercase tracking-[0.8px]" style={{ color: 'var(--color-ash)' }}>
              {l.label}
            </span>
          </div>
        ))}
        {flow.hasGate && (
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-[14px] w-[20px] rounded-[3px] border border-dashed" style={{ borderColor: '#5b5f61' }} />
            <span className="font-mono text-[10.5px] uppercase tracking-[0.8px]" style={{ color: 'var(--color-ash)' }}>
              skipped
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// Small SVG glyphs echoing each Mermaid shape, for the legend.
function LegendGlyph({ shape }: { shape: string }) {
  const s = { width: 22, height: 15 };
  const stroke = 'var(--color-stone)';
  const common = { fill: 'none', stroke, strokeWidth: 1.4 };
  switch (shape) {
    case 'parallelogram':
      return <svg {...s}><polygon points="5,2 21,2 17,13 1,13" {...common} /></svg>;
    case 'stadium':
      return <svg {...s}><rect x="1" y="2" width="20" height="11" rx="5.5" {...common} /></svg>;
    case 'rhombus':
      return <svg {...s}><polygon points="11,1 21,7.5 11,14 1,7.5" {...common} /></svg>;
    case 'hexagon':
      return <svg {...s}><polygon points="5,2 17,2 21,7.5 17,13 5,13 1,7.5" {...common} /></svg>;
    case 'trapezoid':
      return <svg {...s}><polygon points="1,13 5,2 17,2 21,13" {...common} /></svg>;
    case 'circle':
      return <svg {...s}><circle cx="11" cy="7.5" r="6" {...common} /></svg>;
    case 'rect':
    default:
      return <svg {...s}><rect x="1" y="2" width="20" height="11" rx="2" {...common} /></svg>;
  }
}
