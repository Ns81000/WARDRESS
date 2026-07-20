import type { FlowSpec } from '../flows/types';

interface Props {
  flows: FlowSpec[];
  activeId: string;
  onSelect: (id: string) => void;
}

export function TabBar({ flows, activeId, onSelect }: Props) {
  return (
    <div
      role="tablist"
      aria-label="Walkthroughs"
      className="flex items-center gap-1 rounded-[10px] border border-hairline bg-surface-card p-1"
    >
      {flows.map((f) => {
        const active = f.id === activeId;
        return (
          <button
            key={f.id}
            role="tab"
            aria-selected={active}
            onClick={() => onSelect(f.id)}
            className="rounded-[7px] px-3.5 py-1.5 text-[13px] font-medium transition-colors"
            style={{
              background: active ? 'var(--color-surface-elevated)' : 'transparent',
              color: active ? 'var(--color-ink)' : 'var(--color-mute)',
              border: active ? '1px solid var(--color-hairline-strong)' : '1px solid transparent',
            }}
          >
            {f.name}
          </button>
        );
      })}
      <span
        className="ml-1 select-none rounded-[7px] border border-dashed border-hairline px-3 py-1.5 font-mono text-[11px]"
        style={{ color: 'var(--color-stone)' }}
        title="More feature walkthroughs land here"
      >
        + more soon
      </span>
    </div>
  );
}
