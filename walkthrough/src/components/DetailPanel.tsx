import { AnimatePresence, motion } from 'motion/react';
import type { FlowNodeSpec } from '../flows/types';
import { accentOf } from '../lib/accent';

interface Props {
  node: FlowNodeSpec | null;
  onClose: () => void;
}

export function DetailPanel({ node, onClose }: Props) {
  return (
    <AnimatePresence mode="wait">
      {node && (
        <motion.aside
          key={node.id}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 24 }}
          transition={{ duration: 0.28, ease: [0.23, 1, 0.32, 1] }}
          className="pointer-events-auto absolute right-4 top-4 bottom-4 z-20 flex w-[380px] flex-col overflow-hidden rounded-[16px] border border-hairline-strong bg-surface-card/95 backdrop-blur-xl"
          aria-label={`${node.title} details`}
        >
          <DetailBody node={node} onClose={onClose} />
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function DetailBody({ node, onClose }: { node: FlowNodeSpec; onClose: () => void }) {
  const { color, glow } = accentOf(node.accent);

  return (
    <>
      {/* header */}
      <div
        className="relative shrink-0 border-b border-hairline px-6 pb-5 pt-6"
        style={{ background: `linear-gradient(180deg, ${glow}, transparent)` }}
      >
        <span aria-hidden className="absolute inset-y-0 left-0 w-[3px]" style={{ background: color }} />
        <div className="flex items-start justify-between gap-3">
          <div>
            {node.index && (
              <div
                className="font-display leading-none"
                style={{ fontSize: 30, color, fontVariationSettings: '"opsz" 144' }}
              >
                {node.index}
              </div>
            )}
            <h2
              className="font-display-sans text-[22px] font-medium tracking-[-0.3px] text-ink"
              style={{ marginTop: node.index ? 8 : 0 }}
            >
              {node.title}
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close details"
            className="shrink-0 rounded-[8px] border border-hairline px-2 py-1 text-mute transition-colors hover:border-hairline-strong hover:text-ink"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <p className="mt-3 text-[14px] leading-relaxed text-body">{node.detail.plain}</p>
      </div>

      {/* scroll body */}
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {node.detail.math && (
          <Chip label="The math">
            <code className="font-mono text-[12.5px]" style={{ color }}>
              {node.detail.math}
            </code>
          </Chip>
        )}
        {node.detail.inputScope && (
          <Chip label="Input scope">
            <span className="font-mono text-[12.5px] text-body">{node.detail.inputScope}</span>
          </Chip>
        )}

        <div className="mt-5 flex flex-col gap-5">
          {node.detail.blocks.map((b) => (
            <div key={b.label}>
              <h4
                className="font-mono text-[11px] uppercase tracking-[1.2px]"
                style={{ color: 'var(--color-ash)' }}
              >
                {b.label}
              </h4>
              <p className="mt-2 text-[13.5px] leading-relaxed text-charcoal">{b.body}</p>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function Chip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3 rounded-[10px] border border-hairline bg-surface-deep px-4 py-3">
      <div
        className="font-mono text-[10px] uppercase tracking-[1.2px]"
        style={{ color: 'var(--color-ash)' }}
      >
        {label}
      </div>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}
