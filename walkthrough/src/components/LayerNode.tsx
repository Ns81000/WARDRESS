import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { FlowNodeSpec } from '../flows/types';
import { accentOf } from '../lib/accent';

// Visual lifecycle of a node within the step-through machine.
export type NodeState = 'pending' | 'active' | 'done' | 'skipped';

export type WardressNodeData = {
  spec: FlowNodeSpec;
  state: NodeState;
  selected: boolean;
};

export type WardressNode = Node<WardressNodeData, 'wardress'>;

const KIND_WIDTH: Record<FlowNodeSpec['kind'], number> = {
  io: 190,
  stage: 190,
  layer: 214,
  fusion: 214,
  score: 210,
};

export function LayerNode({ data }: NodeProps<WardressNode>) {
  const { spec, state, selected } = data;
  const { color, glow } = accentOf(spec.accent);
  const skipped = state === 'skipped';
  const active = state === 'active';
  const done = state === 'done';
  const dimmed = state === 'pending' || skipped;

  const width = KIND_WIDTH[spec.kind];
  const isScore = spec.kind === 'score';

  // Border + glow intensity follow lifecycle. Active/selected nodes light up
  // in their accent; skipped nodes go dashed and faint; pending sit quiet.
  const borderColor = skipped
    ? 'rgba(255,255,255,0.10)'
    : active || selected || done
      ? color
      : 'var(--color-hairline-strong)';

  const boxShadow =
    active || selected
      ? `0 0 0 1px ${color}, 0 0 28px ${glow}`
      : done
        ? `0 0 16px ${glow}`
        : 'none';

  return (
    <div
      style={{
        width,
        opacity: dimmed ? (skipped ? 0.32 : 0.6) : 1,
        borderColor,
        boxShadow,
        borderStyle: skipped ? 'dashed' : 'solid',
        background: isScore
          ? 'linear-gradient(150deg, var(--color-surface-card), var(--color-surface-deep))'
          : 'var(--color-surface-card)',
        transition:
          'opacity 400ms ease, border-color 400ms ease, box-shadow 400ms ease, transform 300ms ease',
        transform: active ? 'translateY(-2px)' : 'none',
      }}
      className="relative overflow-hidden rounded-[12px] border px-[18px] py-[15px] font-sans"
    >
      {/* left accent bar — the .layer-tile::before signature */}
      <span
        aria-hidden
        style={{ background: color, opacity: skipped ? 0.4 : 1 }}
        className="absolute inset-y-0 left-0 w-[3px]"
      />

      {/* connection handles (visually hidden via CSS; wiring only) */}
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />

      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          {spec.index && (
            <div
              className="font-display leading-none"
              style={{
                fontSize: 22,
                color: active || done ? color : 'var(--color-stone)',
                fontVariationSettings: '"opsz" 144',
              }}
            >
              {spec.index}
            </div>
          )}
          <h3
            className="font-display-sans font-medium tracking-[-0.2px] text-ink"
            style={{ fontSize: isScore ? 16 : 15, marginTop: spec.index ? 8 : 0 }}
          >
            {spec.title}
          </h3>
        </div>

        {isScore && (
          <ScoreReadout state={state} color={color} />
        )}
      </div>

      <p
        className="mt-[6px] text-charcoal"
        style={{ fontSize: 12, lineHeight: 1.5 }}
      >
        {spec.tagline}
      </p>

      <div className="mt-[10px] flex items-center justify-between gap-2">
        {spec.systemKey && (
          <span
            className="font-mono truncate"
            style={{ fontSize: 10.5, color: skipped ? 'var(--color-ash)' : color }}
          >
            {spec.systemKey}
          </span>
        )}
        {skipped && (
          <span
            className="font-mono whitespace-nowrap"
            style={{ fontSize: 9.5, color: 'var(--color-ash)' }}
          >
            skipped · logged
          </span>
        )}
        {spec.gateRole === 'always' && !skipped && (
          <span
            className="font-mono whitespace-nowrap"
            style={{ fontSize: 9.5, color: 'var(--color-ash)' }}
          >
            always runs
          </span>
        )}
      </div>
    </div>
  );
}

// The final node shows a live 0.02 readout once the flow reaches it.
function ScoreReadout({ state, color }: { state: NodeState; color: string }) {
  const revealed = state === 'active' || state === 'done';
  return (
    <div className="text-right">
      <div
        className="font-display leading-none"
        style={{
          fontSize: 34,
          color: revealed ? color : 'var(--color-stone)',
          fontVariationSettings: '"opsz" 144',
          textShadow: revealed ? `0 0 22px ${'rgba(34,255,153,0.35)'}` : 'none',
          transition: 'color 500ms ease, text-shadow 500ms ease',
        }}
      >
        {revealed ? '0.02' : '—'}
      </div>
    </div>
  );
}
