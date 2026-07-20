import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { flows } from './flows';
import { FlowCanvas } from './components/FlowCanvas';
import { DetailPanel } from './components/DetailPanel';
import { TabBar } from './components/TabBar';
import { StepControls } from './components/StepControls';
import { GateToggle, type GateMode } from './components/GateToggle';

// Landing page origin under GitHub Pages (project subpath).
const LANDING_URL = '../';

export function App() {
  const [activeId, setActiveId] = useState(flows[0].id);
  const [step, setStep] = useState(-1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [gateMode, setGateMode] = useState<GateMode>('changed');
  const runTimer = useRef<number | null>(null);

  const flow = useMemo(() => flows.find((f) => f.id === activeId) ?? flows[0], [activeId]);
  const total = flow.steps.length;
  const gateSkipped = flow.hasGate && gateMode === 'identical';

  const clearRun = useCallback(() => {
    if (runTimer.current !== null) {
      window.clearInterval(runTimer.current);
      runTimer.current = null;
    }
  }, []);

  // Reset the machine whenever the flow changes.
  useEffect(() => {
    clearRun();
    setStep(-1);
    setSelectedId(null);
    setGateMode('changed');
  }, [activeId, clearRun]);

  useEffect(() => () => clearRun(), [clearRun]);

  const next = useCallback(() => {
    clearRun();
    setStep((s) => Math.min(s + 1, total - 1));
  }, [clearRun, total]);

  const prev = useCallback(() => {
    clearRun();
    setStep((s) => Math.max(s - 1, 0));
  }, [clearRun]);

  const reset = useCallback(() => {
    clearRun();
    setStep(-1);
    setSelectedId(null);
  }, [clearRun]);

  const runAll = useCallback(() => {
    clearRun();
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) {
      setStep(total - 1);
      return;
    }
    setStep((s) => (s < 0 ? 0 : s));
    runTimer.current = window.setInterval(() => {
      setStep((s) => {
        if (s >= total - 1) {
          clearRun();
          return s;
        }
        return s + 1;
      });
    }, 1100);
  }, [clearRun, total]);

  // Keyboard: arrows step, Escape closes the panel.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') next();
      else if (e.key === 'ArrowLeft') prev();
      else if (e.key === 'Escape') setSelectedId(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [next, prev]);

  const selectedNode = useMemo(
    () => flow.nodes.find((n) => n.id === selectedId) ?? null,
    [flow, selectedId],
  );

  const caption = step >= 0 ? flow.steps[step] : '';

  return (
    <div className="flex h-full flex-col bg-canvas text-body">
      {/* ambient glow field, matching the landing page */}
      <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <div
          className="absolute left-1/2 top-[-320px] h-[720px] w-[720px] -translate-x-[55%] rounded-full"
          style={{ background: 'radial-gradient(circle, var(--color-glow-blue), transparent 68%)', filter: 'blur(120px)', opacity: 0.42 }}
        />
        <div
          className="absolute right-[-220px] top-[6%] h-[520px] w-[520px] rounded-full"
          style={{ background: 'radial-gradient(circle, var(--color-glow-orange), transparent 70%)', filter: 'blur(120px)', opacity: 0.3 }}
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
          <p className="mt-1.5 max-w-[60ch] text-[13.5px] text-charcoal">{flow.blurb}</p>
        </div>
        {flow.hasGate && <GateToggle mode={gateMode} onChange={setGateMode} />}
      </div>

      {/* ===== canvas ===== */}
      <div className="relative z-10 min-h-0 flex-1">
        <FlowCanvas
          flow={flow}
          step={step}
          gateSkipped={gateSkipped}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <DetailPanel node={selectedNode} onClose={() => setSelectedId(null)} />

        {/* hint */}
        {step < 0 && !selectedNode && (
          <div className="pointer-events-none absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-full border border-hairline bg-surface-card/90 px-4 py-1.5 text-[12px] text-mute backdrop-blur-xl">
            Click any node for a deep dive · use the controls below to walk the flow
          </div>
        )}
      </div>

      {/* ===== step controls ===== */}
      <div className="relative z-10 flex shrink-0 justify-center px-6 pb-5 pt-2">
        <StepControls
          step={step}
          total={total}
          caption={caption}
          onPrev={prev}
          onNext={next}
          onReset={reset}
          onRunAll={runAll}
        />
      </div>
    </div>
  );
}
