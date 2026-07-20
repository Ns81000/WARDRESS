interface Props {
  step: number; // -1 = not started
  total: number;
  caption: string;
  onPrev: () => void;
  onNext: () => void;
  onReset: () => void;
  onRunAll: () => void;
}

export function StepControls({ step, total, caption, onPrev, onNext, onReset, onRunAll }: Props) {
  const started = step >= 0;
  const atEnd = step >= total - 1;

  return (
    <div className="flex items-center gap-4 rounded-[12px] border border-hairline bg-surface-card/95 px-4 py-2.5 backdrop-blur-xl">
      <button
        onClick={onReset}
        disabled={!started}
        aria-label="Reset"
        className="rounded-[8px] border border-hairline px-2.5 py-1.5 text-mute transition-colors enabled:hover:border-hairline-strong enabled:hover:text-ink disabled:opacity-40"
      >
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 2v6h6" /><path d="M3 8a9 9 0 1 0 3-6.7L3 4" />
        </svg>
      </button>

      <button
        onClick={onPrev}
        disabled={!started}
        aria-label="Previous step"
        className="rounded-[8px] border border-hairline px-2.5 py-1.5 text-mute transition-colors enabled:hover:border-hairline-strong enabled:hover:text-ink disabled:opacity-40"
      >
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>

      {/* step dots + caption */}
      <div className="flex min-w-[300px] flex-col gap-1.5">
        <div className="flex items-center gap-1.5">
          {Array.from({ length: total }).map((_, i) => (
            <span
              key={i}
              className="h-[3px] flex-1 rounded-full transition-colors duration-300"
              style={{
                background: i <= step ? 'var(--color-accent-blue)' : 'var(--color-hairline-strong)',
                boxShadow: i === step ? '0 0 8px var(--color-glow-blue)' : 'none',
              }}
            />
          ))}
        </div>
        <p className="text-[12px] leading-snug text-body">
          {started ? (
            <>
              <span className="font-mono text-ash">{`0${step + 1}`.slice(-2)}/{`0${total}`.slice(-2)} · </span>
              {caption}
            </>
          ) : (
            <span className="text-mute">Press Step to walk through a scan, one stage at a time.</span>
          )}
        </p>
      </div>

      <button
        onClick={onNext}
        disabled={atEnd}
        className="flex items-center gap-1.5 rounded-[8px] border px-3.5 py-1.5 text-[13px] font-medium transition-colors disabled:opacity-40"
        style={{
          borderColor: atEnd ? 'var(--color-hairline)' : 'var(--color-hairline-strong)',
          background: atEnd ? 'transparent' : 'var(--color-surface-elevated)',
          color: 'var(--color-ink)',
        }}
      >
        {started ? 'Step' : 'Start'}
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>

      <button
        onClick={onRunAll}
        disabled={atEnd}
        className="rounded-[8px] px-3 py-1.5 text-[12.5px] font-medium transition-transform enabled:hover:-translate-y-px disabled:opacity-40"
        style={{ background: '#fcfdff', color: '#000' }}
      >
        Run all
      </button>
    </div>
  );
}
