export type GateMode = 'changed' | 'identical';

interface Props {
  mode: GateMode;
  onChange: (mode: GateMode) => void;
}

// The demo control for the Content-Hash skip decision. Flipping to
// "identical" dims the five gated layers — the pipeline's hero beat.
export function GateToggle({ mode, onChange }: Props) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="font-mono text-[10.5px] uppercase tracking-[1px]" style={{ color: 'var(--color-ash)' }}>
        Content hash
      </span>
      <div className="flex items-center rounded-[8px] border border-hairline bg-surface-card p-0.5">
        <Seg active={mode === 'changed'} accent="#ff2047" onClick={() => onChange('changed')}>
          bytes changed
        </Seg>
        <Seg active={mode === 'identical'} accent="#3b9eff" onClick={() => onChange('identical')}>
          identical
        </Seg>
      </div>
      <kbd
        className="rounded-[5px] border px-1.5 py-0.5 font-mono text-[10px]"
        style={{ borderColor: 'var(--color-hairline-strong)', color: 'var(--color-mute)' }}
        title="Press B to toggle"
      >
        B
      </kbd>
    </div>
  );
}

function Seg({
  active,
  accent,
  onClick,
  children,
}: {
  active: boolean;
  accent: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className="rounded-[6px] px-2.5 py-1 font-mono text-[11px] transition-colors"
      style={{
        background: active ? 'var(--color-surface-elevated)' : 'transparent',
        color: active ? accent : 'var(--color-mute)',
        boxShadow: active ? `inset 0 0 0 1px ${accent}55` : 'none',
      }}
    >
      {children}
    </button>
  );
}
